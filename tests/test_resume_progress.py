#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of tools/resume.py and tools/progress.py (v0.6.0 points 7 and 3): a run rebuilt step by step from the files of
tests/fixtures/finish_run; at each stage resume.py names the step to resume (frame, search, complete, write, annex, verify, apply, deliver,
done) and what is missing, and progress.py renders the matching line (English, then French), the calls and new documents being counted
since the previous line; resume.py never writes a file; a searches file without receipts is reported incomplete."""
import contextlib, io, json, pathlib, shutil, subprocess, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import resume as R, progress as G, finish_run as F   # noqa: E702,E401
FX = P / 'fixtures' / 'finish_run'
SCOPE = '# Scope\n\nT = 2026-10-28. Plugin: biology. Mode: standard.\n\n## Criteria\n- x\n\n## Angles\n1. a\n2. b\n3. c\n4. d\n5. e\n\n## Waves\n'


def files(d): return sorted(str(p.relative_to(d)) for p in d.rglob('*') if p.is_file())


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.d = self.tmp / 'run'; (self.d / 'state').mkdir(parents=True)
        self.journal = [json.loads(l) for l in (FX / 'state' / 'journal.jsonl').read_text().splitlines() if l.strip()]

    def tearDown(self): shutil.rmtree(self.tmp)

    def step(self):
        before = files(self.d); s = R.state(self.d); self.assertEqual(files(self.d), before); return s

    def add_calls(self, rows):
        with open(self.d / 'state' / 'journal.jsonl', 'a') as f:
            for r in rows: f.write(json.dumps(r) + '\n')

    def test_stages(self):
        s = self.step(); self.assertEqual(s['step'], 'frame'); self.assertIn('framing in progress', G.line(self.d))
        (self.d / 'scope.md').write_text(SCOPE)
        s = self.step(); self.assertEqual((s['step'], s['section'], s['angles'], s['T']), ('search', 3, 5, '2026-10-28'))
        self.assertEqual(G.line(self.d), 'VP: framing done, 5 research angles, T = 2026-10-28.')
        (self.d / 'searches').mkdir(); shutil.copy(FX / 'searches' / '1.md', self.d / 'searches' / '1.md'); self.add_calls(self.journal[:2])
        self.assertEqual(self.step()['next_search_number'], 2)
        self.assertIn('1 searcher file(s); since last update 2 gateway call(s), 1 new document(s)', G.line(self.d))
        self.assertIn('since last update 0 gateway call(s), 0 new document(s)', G.line(self.d))
        for n in (2, 3): shutil.copy(FX / 'searches' / f'{n}.md', self.d / 'searches' / f'{n}.md')
        self.add_calls(self.journal[2:])
        s = self.step(); self.assertEqual(s['step'], 'complete'); self.assertIn('no stop recorded', s['missing'][0])
        (self.d / 'searches' / '4.md').write_text('# searcher 4\n(nothing yet)\n')
        self.assertIn('4.md', self.step()['searches_incomplete'])
        (self.d / 'scope.md').write_text(SCOPE + '- Wave 1 (searches 1-3): 3 calls, 2 eligible.\n- Wave 2: 0 new. Wave 3: 0 new. Stop: two waves without new eligible.\n')
        self.assertEqual(self.step()['step'], 'write')
        rep = (FX / 'REPORT.md').read_text(); cut = rep.index('## Synthesis & Insights')
        (self.d / 'REPORT.md').write_text(rep[:cut])
        s = self.step(); self.assertEqual(s['step'], 'write'); self.assertIn('Bibliography', s['missing'][0]); self.assertEqual(s['findings'], 5)
        self.assertIn('writing the report (5 finding(s)', G.line(self.d))
        (self.d / 'REPORT.md').write_text(rep)
        self.assertEqual(self.step()['step'], 'annex'); self.assertIn('extracting the claims', G.line(self.d))
        for f in ('card.json', 'result.json'): shutil.copy(FX / f, self.d / f)
        s = self.step(); self.assertEqual(s['step'], 'verify'); self.assertIn(f"verification of {len(json.loads((FX / 'card.json').read_text())['claims'])} claim(s)", G.line(self.d))
        v = json.loads((FX / 'verdicts.json').read_text()); v['claims'][0]['status'] = 'ABSENT'
        (self.d / 'verdicts.json').write_text(json.dumps(v))
        s = self.step(); self.assertEqual(s['step'], 'apply'); self.assertIn(v['claims'][0]['id'], s['missing'][0])
        (self.d / 'REPORT.md').write_text(rep.replace('Verification: rule', 'Verification: in progress. Rule'))
        shutil.copy(FX / 'verdicts.json', self.d / 'verdicts.json')
        s = self.step(); self.assertEqual(s['step'], 'apply'); self.assertTrue(s['in_progress'])
        (self.d / 'REPORT.md').write_text(rep)
        s = self.step(); self.assertEqual(s['step'], 'deliver'); self.assertIn('VP: verification done', G.line(self.d))
        (self.d / 'searches' / '4.md').unlink()
        with contextlib.redirect_stdout(io.StringIO()): F.finish(self.d, offline=True)
        s = self.step(); self.assertEqual(s['step'], 'done', s['missing'])
        line = G.line(self.d); self.assertTrue(line.startswith('VP: finished.'), line); self.assertIn('REPORT.html', line)
        self.assertTrue(G.line(self.d, lang='fr').startswith('VP : terminé.'))
        (self.d / 'REPORT.md').write_text(rep + '\n')                     # a change after finish_run: deliver again (check 13)
        s = self.step(); self.assertEqual(s['step'], 'deliver'); self.assertIn('13 end steps stale', s['missing'][0])

    def test_french_and_cli(self):
        (self.d / 'scope.md').write_text(SCOPE.replace('Mode: standard.', 'Mode: standard. Report language: fr.'))
        self.assertEqual(G.line(self.d), 'VP : cadrage fait, 5 angles de recherche, T = 2026-10-28.')
        o = subprocess.run([sys.executable, '-I', str(P.parent / 'tools' / 'resume.py'), str(self.d)], capture_output=True, text=True)
        self.assertEqual(o.returncode, 0); self.assertIn('Resume at: search (SKILL.md section 3)', o.stdout)
        (self.d / 'state' / 'progress.json').unlink()
        o = subprocess.run([sys.executable, '-I', str(P.parent / 'tools' / 'progress.py'), str(self.d), '--no-save'], capture_output=True, text=True)
        self.assertIn('cadrage fait', o.stdout); self.assertFalse((self.d / 'state' / 'progress.json').exists())
        o = subprocess.run([sys.executable, '-I', str(P.parent / 'tools' / 'resume.py'), str(self.tmp / 'nope')], capture_output=True, text=True)
        self.assertEqual(o.returncode, 2)


if __name__ == '__main__':
    unittest.main()
