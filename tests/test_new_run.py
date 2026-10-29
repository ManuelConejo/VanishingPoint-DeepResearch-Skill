#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of tools/new_run.py (v0.6.0 point 4): vp-<date>-<ascii slug>/ in the given base, accents and stopwords removed, bounded
length, never an existing directory or file (suffix -2, -3), state/run-start.json written (question, language), command line output."""
import json, pathlib, shutil, subprocess, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import new_run as N   # noqa: E702


class T(unittest.TestCase):
    def setUp(self): self.tmp = pathlib.Path(tempfile.mkdtemp())
    def tearDown(self): shutil.rmtree(self.tmp)

    def test_slug(self):
        self.assertEqual(N.slug("Que sait-on de l'effet du jeûne intermittent sur l'HbA1c dans le diabète ?"), 'effet-jeune-intermittent-hba1c-diabete')
        s = N.slug('What is known about the effectiveness of retrieval-augmented generation against hallucinations in large language models?')
        self.assertTrue(s.startswith('effectiveness-retrieval')); self.assertLessEqual(len(s), N.CHARS); self.assertRegex(s, r'^[a-z0-9-]+$')
        self.assertEqual(N.slug('Straße über Größe'), 'strasse-grosse')
        self.assertEqual(N.slug('???'), 'question'); self.assertNotIn('2020', N.slug('Que savait-on en 2020 du RAG ?'))

    def test_never_overwrites(self):
        q = 'Effet du jeûne intermittent'
        a = N.create(q, self.tmp, '2026-10-29'); b = N.create(q, self.tmp, '2026-10-29')
        self.assertEqual(a.name, 'vp-2026-10-29-effet-jeune-intermittent'); self.assertEqual(b.name, a.name + '-2')
        (self.tmp / (a.name + '-3')).write_text('a file, not a directory')
        c = N.create(q, self.tmp, '2026-10-29'); self.assertEqual(c.name, a.name + '-4')
        self.assertEqual((self.tmp / (a.name + '-3')).read_text(), 'a file, not a directory')
        st = json.loads((a / 'state' / 'run-start.json').read_text()); self.assertEqual((st['question'], st['language']), (q, 'fr'))
        self.assertEqual(sorted(p.name for p in a.iterdir()), ['state'])

    def test_cli(self):
        t = str(P.parent / 'tools' / 'new_run.py')
        o = subprocess.run([sys.executable, '-I', t, 'What is known about RAG?', '--base', str(self.tmp), '--date', '2026-10-29'], capture_output=True, text=True)
        self.assertEqual(o.returncode, 0, o.stderr); first, second = o.stdout.splitlines()[:2]
        self.assertTrue(pathlib.Path(first).is_absolute() and pathlib.Path(first).is_dir()); self.assertEqual(second, 'language: en')
        self.assertEqual(pathlib.Path(first).name, 'vp-2026-10-29-rag')
        o = subprocess.run([sys.executable, '-I', t, 'x', '--base', str(self.tmp / 'missing')], capture_output=True, text=True); self.assertEqual(o.returncode, 2)


if __name__ == '__main__':
    unittest.main()
