#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline tests (analysis B, 2026-10-29): record fields kept in the verifier's source text; identical gateway calls not counted twice."""
import json, pathlib, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P)); sys.path.insert(0, str(P.parent / 'tools'))
import test_gateway as TG   # noqa: E402  (scenario, fake_fetch, CASES)
import gateway as gw        # noqa: E402
import verifier as V        # noqa: E402


class RecordHeader(unittest.TestCase):
    def test_venue_and_law_dates_reach_the_verifier(self):
        recs = {'doi:10.18653/v1/2021.findings-emnlp.320': {'id': 'doi:10.18653/v1/2021.findings-emnlp.320', 'title': 'Retrieval Augmentation',
                                                            'year': '2021', 'journal': 'Findings of the Association for Computational Linguistics: EMNLP 2021',
                                                            'type': 'conference-paper', 'abstract': 'Despite showing human-like abilities ...'},
                'celex:31995L0046': {'id': 'celex:31995L0046', 'doi': 'None', 'title': 'Directive 95/46/EC', 'year': '1995', 'journal': 'EUR-Lex (Cellar)',
                                     'in_force_from': '1995-12-13', 'in_force_to': '2018-05-24', 'in_force': '0', 'declared_void_by': [], 'abstract': 'Whereas ...'}}

        class Fake:
            def read(self, ident): return {'results': recs[ident]}
        card = {'card_id': 'c', 'sources': {'S1': {'doi': '10.18653/v1/2021.findings-emnlp.320'}, 'S2': {'celex': '31995L0046'}},
                'claims': [{'id': 'A1', 'text': 'Published in Findings of EMNLP 2021.', 'source': {'key': 'S1'}},
                           {'id': 'A2', 'text': 'End of validity 2018-05-24.', 'source': {'key': 'S2'}}]}
        with tempfile.TemporaryDirectory() as d:
            s = V.load_sources(card, gateway=Fake(), out_dir=d)
            self.assertIn('journal: Findings of the Association for Computational Linguistics: EMNLP 2021', s['S1']['text'])
            self.assertIn('in_force_to: 2018-05-24', s['S2']['text'])
            self.assertNotIn('doi: None', s['S2']['text']); self.assertNotIn('declared_void_by', s['S2']['text'])
            self.assertTrue(s['S1']['text'].rstrip().endswith('human-like abilities ...'))
            self.assertEqual(s['S1']['origin'], 'abstract')
            again = V.load_sources(card, sources_dir=d)                       # saved source.txt carries the header: fragments stay checkable
            self.assertEqual(again['S1']['text'], s['S1']['text'])

    def test_no_field_no_header(self):
        self.assertEqual(V.record_header({'title': 'x', 'abstract': 'y'}), '')


class Repeats(unittest.TestCase):
    def setUp(self): self.tmp = tempfile.TemporaryDirectory(); self.f0 = gw.fetch
    def tearDown(self): gw.fetch = self.f0; self.tmp.cleanup()

    def test_identical_call_not_counted(self):
        T, docs = TG.scenario(TG.CASES[0]); gw.fetch = TG.fake_fetch(docs, T)
        d = pathlib.Path(self.tmp.name)
        (d / 'p.md').write_text('# P\n## Sources\n```sources\nengines: openalex, arxiv\ncap: 3\n```\n', encoding='utf-8')
        g = gw.Gateway([d / 'p.md'], T=T, run='r', state=d / 'state')
        self.assertEqual(g.read('arxiv:2401.00007')['call'], 1)
        self.assertEqual(g.read('arxiv:2401.00007')['call'], 1)             # repeat: served, not counted
        self.assertEqual(g.search('openalex', 'x')['call'], 2)
        self.assertEqual(g.search('openalex', 'x', n=5)['call'], 3)          # another n: not a repeat
        self.assertIn('CAP', g.search('openalex', 'y')['refusal'])
        self.assertEqual(g.read('arxiv:2401.00007')['call'], 3)             # repeats still served at the cap
        lines = [json.loads(x) for x in (d / 'state' / 'journal.jsonl').read_text().splitlines()]
        self.assertEqual([bool(x.get('repeat')) for x in lines], [False, True, False, False, True])
        other = gw.Gateway([d / 'p.md'], T=T, run='r2', state=d / 'state')  # another run: counted
        self.assertEqual(other.read('arxiv:2401.00007')['call'], 1)
        self.assertNotIn('repeat', json.loads((d / 'state' / 'journal.jsonl').read_text().splitlines()[-1]))

    def test_repeats_bounded_by_cap(self):
        T, docs = TG.scenario(TG.CASES[0]); gw.fetch = TG.fake_fetch(docs, T)
        d = pathlib.Path(self.tmp.name)
        (d / 'p.md').write_text('# P\n## Sources\n```sources\nengines: openalex\ncap: 2\n```\n', encoding='utf-8')
        g = gw.Gateway([d / 'p.md'], T=T, run='r', state=d / 'state')
        g.read('arxiv:2401.00007'); g.read('arxiv:2401.00007'); g.read('arxiv:2401.00007')   # 1 counted + 2 free repeats (= cap)
        self.assertEqual(g.read('arxiv:2401.00007')['call'], 2)             # 3rd repeat: counted
        self.assertIn('CAP', g.read('arxiv:2401.00007')['refusal'])


if __name__ == '__main__':
    unittest.main()
