#!/usr/bin/env python3
"""Offline test of the PRISMA-S output of tools/prisma.py: 16 items numbered and titled from config.json (prisma.s.items); filled from the
gateway journal (sources, interface, verbatim queries, limits, dates, citation searching, direct reads, totals); "not done" when the journal
shows the step was not taken, "not recorded" when the run holds no trace; nothing estimated; the verifier's pool is left out; no journal =
every item "not recorded"; PRISMA-S.md and the prisma_s key are written; export_report --prisma shows the section."""
import json, pathlib, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import prisma as PR   # noqa: E402
import export_report as ER   # noqa: E402

J = [
    {'utc': '2020-01-02T10:00:00+00:00', 'call': 'search-pubmed', 'engine': 'pubmed', 'query': 'asthma AND "child" [tiab]', 'n': 20, 'ids': ['pmid:1', 'pmid:2'], 'excluded': 1, 'T': '2020-01-01'},
    {'utc': '2020-01-03T10:00:00+00:00', 'call': 'search-openalex', 'engine': 'openalex', 'query': 'asthma children', 'n': 12, 'ids': ['pmid:2', 'doi:10.1/A'], 'excluded': 0, 'T': '2020-01-01', 'filters': {'language': 'en'}},
    {'utc': '2020-01-04T10:00:00+00:00', 'call': 'citing', 'engine': None, 'query': 'pmid:1', 'n': 20, 'ids': ['pmid:5'], 'excluded': 0, 'T': '2020-01-01'},
    {'utc': '2020-01-04T11:00:00+00:00', 'call': 'read', 'query': 'pmid:1', 'ids': ['pmid:1'], 'T': '2020-01-01'},
    {'utc': '2020-01-04T11:05:00+00:00', 'call': 'read', 'query': 'pmid:9', 'ids': ['pmid:9'], 'T': '2020-01-01'},
    {'utc': '2020-01-05T10:00:00+00:00', 'call': 'search-clinicaltrials', 'engine': 'verifier-only', 'query': 'SECRET', 'ids': ['nct:NCT00000001'], 'pool': 'verifier', 'T': '2020-01-01'},
]


def run(tmp, journal, name='r'):
    d = pathlib.Path(tmp) / name; (d / 'state').mkdir(parents=True)
    if journal is not None: (d / 'state' / 'journal.jsonl').write_text('\n'.join(json.dumps(e) for e in journal) + '\n')
    return d


class T(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory(); self.tmp = self._t.name
    def tearDown(self): self._t.cleanup()

    def items(self, d): return {i['n']: i for i in PR.prisma_s(d)['items']}

    def test_numbering_and_titles(self):
        it = self.items(run(self.tmp, J))
        self.assertEqual(sorted(it), list(range(1, 17)))
        self.assertEqual(it[8]['title'], 'Full search strategies'); self.assertEqual(it[16]['title'], 'Deduplication')
        self.assertEqual(it[14]['section'], 'Peer review')

    def test_filled_from_journal(self):
        it = self.items(run(self.tmp, J)); txt = lambda n: ' '.join(it[n]['text'])
        self.assertEqual(it[1]['status'], 'filled'); self.assertIn('pubmed (1 call)', txt(1)); self.assertIn('openalex', txt(1)); self.assertNotIn('verifier-only', txt(1))
        self.assertIn('gateway', txt(1))
        self.assertEqual(it[2]['status'], 'filled')
        self.assertIn('"asthma AND \\"child\\" [tiab]"', txt(8)); self.assertNotIn('SECRET', txt(8)); self.assertIn("{\"language\": \"en\"}", txt(8))
        self.assertIn('2020-01-01', txt(9)); self.assertIn('12, 20', txt(9)); self.assertIn('removed 1 record', txt(9))
        self.assertIn('pubmed 2020-01-02', txt(13))
        self.assertEqual(it[5]['status'], 'filled'); self.assertIn('citing: 1 call', txt(5))
        self.assertEqual(it[7]['status'], 'filled'); self.assertIn('pmid:9', txt(7))
        self.assertIn('Records identified', txt(15)); self.assertEqual(it[16]['status'], 'filled')

    def test_not_done_and_not_recorded(self):
        it = self.items(run(self.tmp, J[:1]))
        self.assertEqual(it[3]['status'], 'not done'); self.assertEqual(it[5]['status'], 'not done'); self.assertEqual(it[2]['status'], 'not done')
        for n in (4, 6, 10, 11, 12, 14): self.assertEqual(it[n]['status'], 'not recorded', n)
        self.assertIn('not recorded', ' '.join(it[9]['text']))      # since is not journaled: never invented

    def test_registry_engine_from_config(self):
        j = J + [{'utc': '2020-01-06T10:00:00+00:00', 'call': 'search-clinicaltrials', 'engine': 'clinicaltrials', 'query': 'asthma', 'n': 5, 'ids': ['nct:NCT00000002'], 'T': '2020-01-01'}]
        it = self.items(run(self.tmp, j)); self.assertEqual(it[3]['status'], 'filled'); self.assertIn('clinicaltrials', ' '.join(it[3]['text']))

    def test_since_when_journaled(self):
        j = [dict(J[0], since='2015')]
        self.assertIn('2015', ' '.join(self.items(run(self.tmp, j))[9]['text']))

    def test_no_journal(self):
        it = self.items(run(self.tmp, None))
        self.assertTrue(all(i['status'] == 'not recorded' for i in it.values()))

    def test_files_and_export(self):
        d = run(self.tmp, J)
        data, files = PR.write(d)
        md = (d / 'PRISMA-S.md').read_text()
        self.assertIn('PRISMA-S', md); self.assertIn('**8. Full search strategies**', md); self.assertIn('**3. Study registries**: not done.', md)
        self.assertIn(d / 'PRISMA-S.md', files)
        self.assertEqual(len(json.loads((d / 'prisma.json').read_text())['prisma_s']['items']), 16)
        ex = {i: h for i, t, h in ER.extras(d, prisma=True)}
        self.assertIn('prisma', ex); self.assertIn('prisma-s', ex); self.assertIn('Full search strategies', ex['prisma-s'])
        self.assertNotIn('prisma-s', {i for i, t, h in ER.extras(d)})


if __name__ == '__main__': unittest.main()
