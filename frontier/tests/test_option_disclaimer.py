# SPDX-License-Identifier: Apache-2.0
"""Independent literal oracle for VP's optional Rebound disclaimer and page budget."""
import contextlib
import io
import unittest
from unittest.mock import patch

from .helpers import FRONTIER, HEADER, TempCase, load_tool, mutate, run_tool
from .v2_common import V2


EXPECTED = {
    'en': 'Rebound is an agentic creative aid: it proposes ideas and test plans judged by models, with no guarantee - unlike the rest of VanishingPoint, whose claims are measured.',
    'fr': 'Rebond est une aide cr\xe9ative agentique : il propose des id\xe9es et des plans de test jug\xe9s par des mod\xe8les, sans garantie - contrairement au reste de VanishingPoint, dont les affirmations sont mesur\xe9es.',
}


class DisclaimerTest(TempCase):
    def generate(self, language='en', name='valid_vp'):
        work = self.work(name)
        mutate(work, 'intake.json', lambda d: d.update(language=language))
        result = run_tool('card', work)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return work

    def test_english_card_and_report_start_with_exact_disclaimer(self):
        self.assert_outputs('en')

    def test_french_card_and_report_start_with_exact_disclaimer(self):
        self.assert_outputs('fr')

    def assert_outputs(self, language):
        for name in ('valid_vp', 'valid_novp'):
            with self.subTest(name=name):
                work = self.generate(language, name)
                for filename in ('IDEA-CARD.md', 'IDEA-REPORT.md'):
                    content = (work / filename).read_text(encoding='utf-8')
                    self.assertEqual(content.splitlines()[0], EXPECTED[language])
                    self.assertEqual(content.count(EXPECTED[language]), 1)
                    if name == 'valid_novp':
                        self.assertEqual(content.splitlines()[1], HEADER)
                self.assertLessEqual(len((work / 'IDEA-CARD.md').read_text().splitlines()), 80)
                self.assertEqual(load_tool('check').problems(work), [])

    def test_unsupported_and_missing_language_fall_back_to_english(self):
        card = load_tool('card')
        for language in ('de', None):
            mutate(self.work(), 'intake.json', lambda d: d.update(language=language))
            if language is None:
                mutate(self.work(), 'intake.json', lambda d: d.pop('language'))
            for full in (False, True):
                self.assertEqual(card.render(self.work(), full=full).splitlines()[0], EXPECTED['en'])

    def test_unsupported_language_passes_normal_checks_end_to_end(self):
        work = self.generate('de')
        for filename in ('IDEA-CARD.md', 'IDEA-REPORT.md'):
            self.assertEqual((work / filename).read_text(encoding='utf-8').splitlines()[0], EXPECTED['en'])
        result = run_tool('check', work)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_checker_requires_the_first_physical_line(self):
        for language in ('en', 'fr'):
            for name in ('valid_vp', 'valid_novp'):
                work = self.generate(language, name)
                for filename in ('IDEA-CARD.md', 'IDEA-REPORT.md'):
                    path = work / filename
                    original = path.read_text(encoding='utf-8')
                    for prefix in ('\n', '   ', '\ufeff'):
                        with self.subTest(language=language, name=name, filename=filename, prefix=repr(prefix)):
                            path.write_text(prefix + original, encoding='utf-8')
                            result = run_tool('check', work)
                            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                            code = '[DISCLAIMER]' if filename == 'IDEA-CARD.md' else '[REPORT-STALE]'
                            self.assertIn(code, result.stdout)
                    path.write_text(original, encoding='utf-8')

    def test_checker_rejects_missing_altered_moved_or_wrong_language(self):
        for language in ('en', 'fr'):
            for damage in ('missing', 'altered', 'moved', 'wrong language'):
                with self.subTest(language=language, damage=damage):
                    work = self.generate(language)
                    path = work / 'IDEA-CARD.md'
                    lines = path.read_text(encoding='utf-8').splitlines()
                    # Remove the literal, wherever the pre-change renderer put it.
                    lines = [line for line in lines if line != EXPECTED[language]]
                    if damage == 'altered':
                        lines.insert(0, EXPECTED[language].replace(' - ', ' / '))
                    elif damage == 'moved':
                        lines.append(EXPECTED[language])
                    elif damage == 'wrong language':
                        lines.insert(0, EXPECTED['fr' if language == 'en' else 'en'])
                    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
                    result = run_tool('check', work)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn('[DISCLAIMER]', result.stdout)

    def test_report_without_disclaimer_is_stale(self):
        work = self.generate()
        path = work / 'IDEA-REPORT.md'
        path.write_text(path.read_text().replace(EXPECTED['en'] + '\n', ''), encoding='utf-8')
        result = run_tool('check', work)
        self.assertEqual(result.returncode, 1)
        self.assertIn('[REPORT-STALE]', result.stdout)

    def test_print_command_english_french_and_fallback(self):
        for language, expected in ((None, 'en'), ('en', 'en'), ('fr', 'fr'), ('de', 'en')):
            with self.subTest(language=language):
                args = ['--disclaimer'] + (['--lang', language] if language else [])
                result = run_tool('card', *args, cwd=self.tmp)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout, EXPECTED[expected] + '\n')
                self.assertEqual(list(self.tmp.glob('IDEA-*.md')), [])

    def test_print_command_can_read_intake_language(self):
        mutate(self.work(), 'intake.json', lambda d: d.update(language='fr'))
        result = run_tool('card', self.work(), '--disclaimer')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, EXPECTED['fr'] + '\n')
        self.assertFalse((self.work() / 'IDEA-CARD.md').exists())

    def test_page_boundary_counts_disclaimer_within_80_lines(self):
        work = self.generate()
        check = load_tool('check')
        content = (work / 'IDEA-CARD.md').read_text(encoding='utf-8')
        lines = content.splitlines()
        self.assertEqual(lines[0], EXPECTED['en'])
        self.assertEqual(check.CARD_MAX_LINES, 80)
        at_limit = content + '\n' * (80 - len(lines))
        self.assertEqual(len(at_limit.splitlines()), 80)
        self.assertEqual(check.card_text_problems(work, at_limit), [])
        self.assertTrue(any(p.startswith('[CARD]') for p in check.card_text_problems(work, at_limit + '\n')))
        card = load_tool('card')
        with patch.object(card, '_render', return_value=at_limit + '\n'):
            with self.assertRaises(card.CardSizeError):
                card.render(work)
            # Exercise the writing command too: neither new nor existing files
            # may be touched when the rendered card exceeds the page budget.
            for existing in (True, False):
                with self.subTest(existing=existing):
                    if not existing:
                        (work / 'IDEA-CARD.md').unlink()
                        (work / 'IDEA-REPORT.md').unlink()
                    before = {p.relative_to(work): p.read_bytes() for p in work.rglob('*') if p.is_file()}
                    with patch.object(card.common, 'atomic_write', wraps=card.common.atomic_write) as write, \
                            contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(card.main([str(work)]), 1)
                    write.assert_not_called()
                    after = {p.relative_to(work): p.read_bytes() for p in work.rglob('*') if p.is_file()}
                    self.assertEqual(after, before)


class CompactedDisclaimerTest(V2):
    def test_v2_compaction_keeps_disclaimer_on_its_own_first_line(self):
        work = self.to_v2()
        for language in ('en', 'fr'):
            mutate(work, 'intake.json', lambda d: d.update(language=language))
            card = load_tool('card')
            compacted = card.compact_v2(EXPECTED[language] + '\nSupporting line\nAnother field\n')
            self.assertEqual(compacted.splitlines()[0], EXPECTED[language])
            result = run_tool('card', work)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for filename in ('IDEA-CARD.md', 'IDEA-REPORT.md'):
                content = (work / filename).read_text(encoding='utf-8')
                self.assertEqual(content.splitlines()[0], EXPECTED[language])
                if filename == 'IDEA-CARD.md':
                    self.assertLessEqual(len(content.splitlines()), 80)
            self.assertEqual(load_tool('check').problems(work), [])


class HostDisclaimerTest(unittest.TestCase):
    def test_host_prints_disclaimer_before_starting(self):
        text = (FRONTIER / 'SKILL.md').read_text(encoding='utf-8')
        opening = text.split('## Permanent rules')[0]
        self.assertIn('BEFORE starting the run', opening)
        self.assertIn('tools/card.py --disclaimer', opening)
        self.assertIn('--lang fr', opening)
        self.assertIn('intake.json', opening)
        self.assertIn('first physical line', opening)
        self.assertIn('executed test results', opening)
        # Production text has a single source; the host reads the tool's output.
        for expected in EXPECTED.values():
            self.assertNotIn(expected, text)
