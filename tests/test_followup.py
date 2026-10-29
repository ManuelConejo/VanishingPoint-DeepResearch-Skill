#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of the follow-up in the conversation (tools/followup.py, v0.6.0 point 5): on a finished copy of tests/fixtures/finish_run,
followup.py creates followups/1 (then 2) with followup.json (T and plugins inherited, request language, the finding the request points to),
a scope.md skeleton listing the parent's sources as known, the parent's gateway cache hard-linked, and writes no file of the parent; the
follow-up is checked with the bounds of config `followup` (1 to 3 findings, shorter summary, 1 search); finish_run.py on it delivers
<parent>/FOLLOWUP-1.md / .html (no SUMMARY.md unless --summary), and the parent still validates with its fingerprints unchanged (check 13)."""
import contextlib, hashlib, io, json, os, pathlib, shutil, subprocess, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import followup as FW, finish_run as F, validate_card as V, resume as R   # noqa: E402,E401
FX = P / 'fixtures' / 'finish_run'
WORDS = ('La supplémentation en vitamine D seule ne réduit pas les chutes chez les femmes âgées vivant à domicile selon la méta-analyse lue [1]. '
         'Le résultat porte sur la population générale et non sur les femmes carencées, que la source ne distingue pas. ') * 4


def child_report(findings=1):
    f = ''.join(f'### Constat {i} — Aucun effet moyen chez les femmes\n\nLa méta-analyse ne montre aucun effet sur les chutes [1]. Elle ne distingue '
                f'pas les femmes carencées [1]. Conséquence : la question reste ouverte pour ce sous-groupe.\n\nVerdict : ouvert.\n\n' for i in range(1, findings + 1))
    return ('# Complément : les femmes\n\n## Résumé\n\n' + WORDS + '\n\n## Introduction\n\nT et périmètre hérités du rapport principal [1].\n\n'
            '## Analyse principale\n\n' + f + '## Synthèse et enseignements\n\nUn seul ensemble de sources [1].\n\n## Limites et réserves\n\nUne seule source [1].\n\n'
            '## Recommandations\n\nChercher des essais chez les femmes carencées.\n\n## Bibliographie\n\n[1] Auteurs. Calcium, vitamin D... 2026. pmid:42161415. Basis: abstract.\n\n'
            '## Annexe méthodologique\n\nCouverture des sources. Actives : pubmed. Ignorées : aucune.\n\nVérification : 1 affirmation, FOUND 1.\n\nRésumé en une ligne : pas d\'effet moyen.\n')


def tree_hash(d, skip):
    out = {}
    for p in sorted(d.rglob('*')):
        rel = p.relative_to(d)
        if p.is_file() and not any(str(rel).startswith(s) for s in skip): out[str(rel)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.p = self.tmp / 'run'; shutil.copytree(FX, self.p)
        (self.p / 'state' / 'cache').mkdir(); (self.p / 'state' / 'cache' / 'abc').write_bytes(b'cached answer')
        with contextlib.redirect_stdout(io.StringIO()): r = F.finish(self.p, offline=True)
        self.assertTrue(r['validation_passed'])

    def tearDown(self): shutil.rmtree(self.tmp)

    def test_followup(self):
        before = tree_hash(self.p, ('followups', 'FOLLOWUP-'))
        m = FW.prepare(self.p, 'Creuse le point 3 : et chez les femmes ?')
        c = pathlib.Path(m['dir'])
        self.assertEqual(c, (self.p / 'followups' / '1').resolve()); self.assertEqual((m['n'], m['T'], m['language']), (1, '2026-10-28', 'fr'))
        self.assertEqual(m['point']['n'], 3); self.assertIn('doses', m['point']['title'])
        self.assertEqual(m['run'], 'fx-f1'); self.assertEqual(m['cap'], V.FOLLOWUP['call_cap']); self.assertEqual(m['cache_files_linked'], 1)
        self.assertEqual(os.stat(c / 'state' / 'cache' / 'abc').st_ino, os.stat(self.p / 'state' / 'cache' / 'abc').st_ino)
        sc = (c / 'scope.md').read_text()
        self.assertIn('T = 2026-10-28', sc); self.assertNotIn('Report language', sc); self.assertIn('S4: pmid:32492153', sc); self.assertIn('Point developed: Finding 3', sc)
        self.assertEqual(R.state(c)['step'], 'frame')
        self.assertEqual(tree_hash(self.p, ('followups', 'FOLLOWUP-')), before)
        # the follow-up run itself (what the searchers, the annex and the verifier would write)
        (c / 'scope.md').write_text(sc.replace('Write here 1 to 3 numbered angles', '1. women\n\nWrite here'))
        (c / 'searches').mkdir(); (c / 'searches' / '1.md').write_text('# searches/1.md\n1. search-pubmed "vitamin D falls women" -> pmid:42161415\n')
        (c / 'state' / 'journal.jsonl').write_text(json.dumps({'utc': '2026-10-29T10:00:00Z', 'run': 'fx-f1', 'T': '2026-10-28', 'call': 'search-pubmed',
                                                               'ids': ['pmid:42161415']}) + '\n')
        card = {'card_id': 'fx-f1', 'question': m['request'], 'sources': {'S1': {'pmid': '42161415', 'title': 'Calcium, vitamin D'}},
                'claims': [{'id': 'A1', 'text': 'no effect on falls', 'source': {'key': 'S1'}, 'location': 'abstract'}]}
        (c / 'card.json').write_text(json.dumps(card)); (c / 'verdicts.json').write_text(json.dumps({'claims': [{'id': 'A1', 'status': 'FOUND'}]}))
        shutil.copy(FX / 'result.json', c / 'result.json')
        (c / 'REPORT.md').write_text(child_report(4))
        self.assertTrue(any('1 to 3 expected' in x for x in V.problems(c)))
        (c / 'REPORT.md').write_text(child_report(1))
        self.assertEqual([x for x in V.problems(c) if not x.startswith('9 ')], [])
        with contextlib.redirect_stdout(io.StringIO()): r = F.finish(c, offline=True)
        self.assertTrue(r['validation_passed'], r['steps'])
        st = {s['step']: s['status'] for s in r['steps']}; self.assertEqual(st['followup_deliver'], 'ok', r['steps'][-1]); self.assertNotIn('summary', st)
        self.assertFalse((c / 'SUMMARY.md').exists())
        with contextlib.redirect_stdout(io.StringIO()): r = F.finish(c, offline=True, summary=True)          # optional step 8 (--summary)
        self.assertEqual((self.p / 'FOLLOWUP-1.md').read_text(), child_report(1)); self.assertTrue((self.p / 'FOLLOWUP-1.html').is_file())
        summ = (c / 'SUMMARY.md').read_text(); self.assertIn('**Complément 1 — Réponse**', summ); self.assertIn(str((self.p / 'FOLLOWUP-1.html').resolve()), summ)
        self.assertEqual(tree_hash(self.p, ('followups', 'FOLLOWUP-')), before)
        self.assertEqual(V.problems(self.p) + V.end_problems(self.p), [])
        self.assertEqual(FW.prepare(self.p, 'and for France?')['n'], 2)

    def test_refusals_and_cli(self):
        t = str(P.parent / 'tools' / 'followup.py')
        o = subprocess.run([sys.executable, '-I', t, str(self.p), 'dig into finding 2'], capture_output=True, text=True)
        self.assertEqual(o.returncode, 0, o.stderr); lines = o.stdout.splitlines()
        self.assertTrue(lines[0].endswith('followups/1')); self.assertIn('--cap', lines[2]); self.assertIn('FOLLOWUP-1.md', lines[4])
        o = subprocess.run([sys.executable, '-I', t, lines[0], 'again'], capture_output=True, text=True)
        self.assertEqual(o.returncode, 2); self.assertIn('no REPORT.md', o.stderr)
        (self.p / 'REPORT.md').rename(self.p / 'R.md')
        self.assertEqual(subprocess.run([sys.executable, '-I', t, str(self.p), 'x'], capture_output=True).returncode, 2)


if __name__ == '__main__':
    unittest.main()
