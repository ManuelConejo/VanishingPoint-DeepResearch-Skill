# SPDX-License-Identifier: Apache-2.0
"""new_run.py: creates frontier-YYYY-MM-DD-<subject>/, never an existing one (regression specification R6)."""
import re
import unittest
from pathlib import Path

from .helpers import TempCase, load_tool, run_tool


class NewRunTest(TempCase):
    def test_creates_dated_directory(self):
        r = run_tool('new_run', 'Short titles & citations: a retrieval story?', '--parent', self.tmp, '--date', '2026-11-14')
        self.assertEqual(r.returncode, 0, r.stderr)
        p = Path(r.stdout.strip())
        self.assertTrue(p.is_absolute())
        self.assertTrue(p.is_dir())
        self.assertEqual(p.parent, self.tmp.resolve())
        self.assertTrue(re.fullmatch(r'frontier-2026-11-14-[a-z0-9-]+', p.name), p.name)
        self.assertIn('short-titles', p.name)

    def test_never_existing(self):
        names = []
        for _ in range(3):
            r = run_tool('new_run', 'same idea', '--parent', self.tmp, '--date', '2026-11-14')
            self.assertEqual(r.returncode, 0, r.stderr)
            names.append(Path(r.stdout.strip()).name)
        self.assertEqual(names, ['frontier-2026-11-14-same-idea', 'frontier-2026-11-14-same-idea-2',
                                 'frontier-2026-11-14-same-idea-3'])

    def test_default_date_is_today(self):
        import datetime
        r = run_tool('new_run', 'x', '--parent', self.tmp)
        self.assertIn('frontier-' + datetime.date.today().isoformat(), r.stdout)

    def test_slug(self):
        slug = load_tool('new_run').slug
        self.assertEqual(slug('\u00c9tude des r\u00e9veils tardifs'), 'etude-des-reveils-tardifs')
        self.assertEqual(slug('!!!'), 'idea')
        self.assertLessEqual(len(slug('word ' * 40)), 40)
        self.assertFalse(slug('word ' * 40).endswith('-'))

    def test_bad_date_refused(self):
        r = run_tool('new_run', 'x', '--parent', self.tmp, '--date', '14/11/2026')
        self.assertNotEqual(r.returncode, 0)


if __name__ == '__main__':
    unittest.main()
