#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of tools/followups.py (follow-up questions, optional): every question is a fixed template filled from the run's files
(no model): DISTORTED and ABSENT claims, claims removed after verification and named in result.json / the methodology appendix,
SOURCE-UNAVAILABLE claims, sources the verifier could not obtain, identifiers the searchers could not read, scope angles whose searches/
files hold no cited source, empty angles stated in the report, conflicts named by the verifier, contradictor "false detected"; 3 to 5
questions, the families taken in turn; fewer derivable = fewer written (never invented); nothing derivable = none; FOLLOWUPS.md and
followups.json written; the HTML export shows them only with --followups, escaped; finish_run.py --followups runs the step."""
import contextlib, io, json, pathlib, shutil, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import followups as FU   # noqa: E402
import export_report as ER   # noqa: E402
import finish_run as F   # noqa: E402

CARD = {'card_id': 'x', 'question': 'q', 'sources': {'S1': {'doi': '10.1/a', 'title': 'Alpha study'}, 'S2': {'pmid': '22', 'title': 'Beta <trial>'},
                                                     'S3': {'pmid': '33', 'title': 'Gamma'}},
        'claims': [{'id': 'A1', 'text': 'Alpha reduces X by 20 %', 'source': {'key': 'S1'}, 'location': 'abstract'},
                   {'id': 'A2', 'text': 'Beta enrolled 300 <children>', 'source': {'key': 'S2'}, 'location': 'abstract'},
                   {'id': 'A3', 'text': 'Gamma finds no effect', 'source': {'key': 'S3'}, 'location': 'abstract'},
                   {'id': 'A4', 'text': 'Alpha is the largest trial', 'source': {'key': 'S1'}, 'location': 'abstract'},
                   {'id': 'A5', 'text': 'Gamma is randomised', 'source': {'key': 'S3'}, 'location': 'abstract'}]}
VER = {'claims': [{'id': 'A1', 'status': 'DISTORTED', 'discrepancy': 'figure: card 20 %, source 12 %'},
                  {'id': 'A2', 'status': 'SOURCE-UNAVAILABLE', 'discrepancy': 'record only, no abstract'},
                  {'id': 'A3', 'status': 'DISTORTED', 'discrepancy': 'direction: the source contradicts the card, it reports an increase'},
                  {'id': 'A4', 'status': 'FOUND'}, {'id': 'A5', 'status': 'FOUND'}]}
SCOPE = """# Scope
## Angles
1. Core trials of alpha. Calls ~8.
2. Paediatric populations and long follow-up. Engines: pubmed.
3. Negative results.
## Budget
"""
REPORT = """# R
## Executive Summary
x
## Limitations & Caveats
Empty angles: cost-effectiveness; adverse events in adults. No source seen on long-term outcomes beyond five years.
## Methodology Appendix
Verification: Removals (ABSENT): A9 (the dose-response claim of Finding 2); A10 without description. Kept: A4.
"""


def make(d, all_found=False):
    (d / 'searches').mkdir(parents=True); (d / 'state').mkdir()
    (d / 'card.json').write_text(json.dumps(CARD))
    v = {'claims': [{'id': c['id'], 'status': 'FOUND'} for c in CARD['claims']]} if all_found else VER
    (d / 'verdicts.json').write_text(json.dumps(v))
    if all_found: return
    (d / 'scope.md').write_text(SCOPE); (d / 'REPORT.md').write_text(REPORT)
    (d / 'result.json').write_text(json.dumps({'studies': [], 'verification': {'entries_removed': 0, 'rule': 'after verification: A9 (ABSENT, dose-response) removed'}}))
    (d / 'searches' / '1.md').write_text('# searches/1.md (angles 1 and 3)\n- doi:10.1/a | Alpha | probable\n')
    (d / 'searches' / '2.md').write_text('# searches/2.md — angle 2 (paediatric)\n- pmid:99 | Delta | possible\n')
    (d / 'state' / 'verifier.json').write_text(json.dumps({'per_source': {'S1': {'origin': 'abstract'}, 'S3': {'origin': 'missing'}}}))
    (d / 'state' / 'journal.jsonl').write_text('\n'.join(json.dumps(e) for e in [
        {'call': 'search-pubmed', 'engine': 'pubmed', 'query': 'q', 'ids': ['pmid:22', 'pmid:99'], 'T': '2021-05-01'},
        {'call': 'read', 'query': 'pmid:77', 'ids': [None], 'T': '2021-05-01'},
        {'call': 'read', 'query': 'pmid:22', 'ids': ['pmid:22'], 'T': '2021-05-01'}]) + '\n')
    (d / 'contradictor.json').write_text(json.dumps({'elements': [{'status': 'false detected', 'family': 'openai', 'quote': 'X doubles Y', 'why': 'the cited file says halves', 'position': 'Finding 1'},
                                                                  {'status': 'false added: ABSENT', 'family': 'openai', 'quote': 'no'}]}))


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.d = self.tmp / 'run'; make(self.d)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_candidates(self):
        c = FU.candidates(self.d); txt = {f: [q['text'] for q in c[f]] for f in c}
        v = ' '.join(txt['verification'])
        self.assertIn('What do sources other than [1] report on "Alpha reduces X by 20 %"? The verifier found that [1] does not support it as written: figure: card 20 %, source 12 %.', v)
        self.assertIn('supports "dose-response"? The claim (A9) was removed after verification', v)   # from result.json, first
        self.assertNotIn('A10', v); self.assertNotIn('(A4)', v)          # no description / still present: nothing to ask
        self.assertTrue(c['verification'][0]['from'].startswith('removal'))   # removals before corrections
        u = ' '.join(txt['unavailable'])
        self.assertIn('Does the full text of [2] (Beta <trial>) support "Beta enrolled 300 <children>"?', u)
        self.assertIn('[3] (Gamma)', u); self.assertIn('pmid:77', u); self.assertNotIn('pmid:22 say', u)
        a = ' '.join(txt['angle'])
        self.assertIn('angle 2 of the scope, "Paediatric populations and long follow-up"', a)    # its file cites nothing of the card
        self.assertNotIn('angle 1 ', a); self.assertNotIn('angle 3 ', a)
        for w in ('cost-effectiveness', 'adverse events in adults', 'long-term outcomes beyond five years'): self.assertIn(w, a)
        k = ' '.join(txt['contradiction'])
        self.assertIn('Which reading holds for "Gamma finds no effect"? The verifier noted a conflict with [3]', k)
        self.assertIn('Is "X doubles Y" right? A contradictor of another model family (openai) disputed it: the cited file says halves.', k)
        self.assertNotIn('"no"', k)
        for f, qs in c.items():
            for q in qs: self.assertEqual(q['family'], f)

    def test_build_and_files(self):
        x = FU.build(self.d)
        self.assertEqual(len(x['questions']), FU.CFG['max'])
        self.assertEqual([q['family'] for q in x['questions'][:4]], list(FU.FAMILIES))   # families in turn
        self.assertFalse(x['short'])
        ids = [q['refs'][0] for q in x['questions'] if q['refs'] and q['refs'][0].startswith('A')]
        self.assertEqual(len(ids), len(set(ids)))                    # A3 (DISTORTED naming a conflict) asked once
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(FU.main([str(self.d)]), 0)
        md = (self.d / 'FOLLOWUPS.md').read_text()
        self.assertTrue(md.startswith('# Follow-up questions')); self.assertIn('no model wrote them', md)
        self.assertEqual(len([l for l in md.splitlines() if l[:2] in ('1.', '2.', '3.', '4.', '5.')]), 5)
        self.assertEqual(json.loads((self.d / 'followups.json').read_text())['questions'], x['questions'])

    def test_short_and_none(self):
        d = self.tmp / 'clean'; make(d, all_found=True)
        x = FU.build(d); self.assertEqual(x['questions'], []); self.assertIn('No follow-up question is derivable', FU.markdown(x))
        d2 = self.tmp / 'one'; make(d2, all_found=True)
        (d2 / 'verdicts.json').write_text(json.dumps({'claims': [{'id': 'A1', 'status': 'DISTORTED', 'discrepancy': 'scope'}] + [{'id': f'A{i}', 'status': 'FOUND'} for i in range(2, 6)]}))
        x = FU.build(d2); self.assertEqual(len(x['questions']), 1); self.assertTrue(x['short'])
        self.assertIn('none was invented', FU.markdown(x))

    def test_html_option(self):
        (self.d / 'REPORT.md').write_text(REPORT)
        h0 = ER.render(REPORT, extra=ER.extras(self.d))
        self.assertNotIn('Follow-up questions', h0)
        h = ER.render(REPORT, extra=ER.extras(self.d, followups=True))
        self.assertIn('<h2 id="followups" class="pb">Follow-up questions</h2>', h); self.assertIn('href="#followups"', h)
        self.assertIn('Beta &lt;trial&gt;', h); self.assertNotIn('<children>', h); self.assertNotIn('<trial>', h)

    def test_finish_option(self):
        d = self.tmp / 'fr'; shutil.copytree(P / 'fixtures' / 'finish_run', d)
        fetch = F.gw.fetch; F.gw.fetch = lambda *a, **k: (_ for _ in ()).throw(OSError('offline test'))
        try:
            r = F.finish(d, offline=True, followups=True)
        finally:
            F.gw.fetch = fetch
        st = {s['step']: s['status'] for s in r['steps']}
        self.assertEqual(st['followups'], 'ok'); self.assertTrue((d / 'FOLLOWUPS.md').is_file())
        self.assertIn('Follow-up questions', (d / 'REPORT.html').read_text())
        self.assertNotIn('prisma', st)


if __name__ == '__main__':
    unittest.main()
