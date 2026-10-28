#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of tools/prisma.py (PRISMA 2020 flow diagram, optional): on a synthetic run, the boxes are counted from the journal
(search pool only; the verifier's pool is left out): identified per source with the date barrier, duplicates, records without
identifier, direct reads, reads failed or refused = not retrieved; exclusion reasons read from the searchers' marks (inline, in the
identifier's own parentheses, under a label, under a heading; "excluded-leaning" and gateway exclusions are not decisions); included from
card.json / result.json; the arithmetic of the boxes closes; a missing input is "not recorded", never a number; the SVG is well-formed
and escapes the text; the option is off by default in finish_run.py and export_report.py and on with --prisma."""
import contextlib, io, json, pathlib, shutil, sys, tempfile, unittest
import xml.etree.ElementTree as ET
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import prisma as PR   # noqa: E402
import finish_run as F   # noqa: E402
import export_report as ER   # noqa: E402

J = [
    {'call': 'search-pubmed', 'engine': 'pubmed', 'query': 'q1', 'ids': ['pmid:1', 'pmid:2', 'pmid:3', None], 'excluded': 2, 'T': '2020-01-01'},
    {'call': 'search-openalex', 'engine': 'openalex', 'query': 'q2', 'ids': ['pmid:2', 'doi:10.1/A', 'pmid:4'], 'excluded': 0, 'T': '2020-01-01'},
    {'call': 'citing', 'engine': None, 'query': 'pmid:1', 'ids': ['pmid:5', 'pmid:1'], 'excluded': 3, 'T': '2020-01-01'},
    {'call': 'read', 'query': 'pmid:1', 'ids': ['pmid:1'], 'T': '2020-01-01'},
    {'call': 'read', 'query': 'pmid:2', 'ids': ['pmid:2'], 'T': '2020-01-01'},
    {'call': 'read', 'query': 'pmid:3', 'ids': ['pmid:3'], 'T': '2020-01-01'},
    {'call': 'read', 'query': 'DOI:10.1/a', 'ids': [None], 'T': '2020-01-01'},                 # refused (after T): not retrieved
    {'call': 'read', 'query': 'pmid:4', 'ids': [], 'error': 'HTTPError 500', 'T': '2020-01-01'},  # failed: not retrieved
    {'call': 'read', 'query': 'pmid:9', 'ids': ['pmid:9'], 'T': '2020-01-01'},                  # direct read (never returned by a search)
    {'call': 'read', 'query': 'pmid:6', 'ids': ['pmid:6'], 'pool': 'verifier', 'T': '2020-01-01'},   # verifier pool: left out
    {'call': 'search-pubmed', 'engine': 'pubmed', 'query': 'v', 'ids': ['pmid:7'], 'pool': 'verifier', 'T': '2020-01-01'},
]
SEARCH1 = """# searches/1.md (angles 1 and 2)
- pmid:2 | Some title | 2019 | basis abstract | EXCLUDED (case report <i>)
- pmid:3 | Other | 2018 | title | excluded-leaning (maybe)
Note: 4 documents excluded post-T by the gateway: pmid:1
"""
SEARCH2 = """# searches/2.md
Seen-not-kept: pmid:5 (Smith 2010; read: two patients, excluded <script>), pmid:9 (Doe, kept for context)
"""
SEARCH3 = """# searches/3.md

EXCLUDED (with reason):
- pmid:3 Fahmida 2015 - abstract: quasi-experimental - non-randomised
"""


def make(d, journal=True, card=True, result=True):
    (d / 'searches').mkdir(parents=True)
    for n, t in enumerate((SEARCH1, SEARCH2, SEARCH3), 1): (d / 'searches' / f'{n}.md').write_text(t)
    if journal:
        (d / 'state').mkdir()
        (d / 'state' / 'journal.jsonl').write_text('\n'.join(json.dumps(e) for e in J) + '\nnot json\n')
    if card:
        (d / 'card.json').write_text(json.dumps({'card_id': 'x', 'question': 'q', 'sources': {'S1': {'pmid': '1', 'title': 't'}, 'S2': {'doi': '10.1/zz', 'title': 'u'}},
                                                 'claims': []}))
    if result:
        (d / 'result.json').write_text(json.dumps({'studies': [{'id': 'pmid:1'}], 'verification': {'entries_removed': 1, 'rule': 'after verification'}}))


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.d = self.tmp / 'run'

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_numbers(self):
        make(self.d); x = PR.build(self.d)
        idf, sc, inc = x['identification'], x['screening'], x['included']
        self.assertEqual(idf['per_source']['pubmed'], {'records': 6, 'date_barrier': 2, 'calls': 1})          # 4 returned (one without id) + 2 barrier
        self.assertEqual(idf['per_source']['openalex']['records'], 3)
        self.assertEqual(idf['per_source']['citation searching (citing/references/related)']['records'], 5)
        self.assertEqual(idf['per_source']['direct read (identifier not returned by a search)']['records'], 1)  # pmid:9
        self.assertEqual(idf['identified'], 15)
        self.assertEqual(idf['removed_before_screening'], {'duplicates': 2, 'date_barrier': 5, 'automation': PR.NR})
        self.assertEqual(idf['records_without_identifier'], 1)
        self.assertEqual(sc['screened'], 8)                       # pmid 1,2,3,4,5,9 + doi:10.1/a + 1 without id
        self.assertEqual(idf['identified'] - 2 - 5, sc['screened'])   # the arithmetic closes
        self.assertEqual((sc['sought'], sc['not_retrieved'], sc['assessed']), (6, 2, 4))
        self.assertEqual(sc['not_retrieved_ids'], ['doi:10.1/a', 'pmid:4'])
        self.assertEqual(sc['excluded_at_screening'], 2)
        self.assertEqual((inc['reports'], inc['studies'], inc['entries_removed_after_verification']), (2, 1, 1))
        self.assertEqual((sc['included_from_assessed'], sc['included_without_read']), (1, 1))
        self.assertEqual(sc['reports_excluded'], 3)               # pmid 2, 3, 9 assessed and not cited
        r = {x['reason']: x['ids'] for x in sc['reasons']}
        self.assertEqual(r['case report <i>'], ['pmid:2'])
        self.assertEqual(r['non-randomised'], ['pmid:3'])         # under the "EXCLUDED (with reason):" label, not the "-leaning" line
        self.assertEqual(r['reason not recorded'], ['pmid:9'])    # "kept for context": no exclusion mark
        self.assertNotIn('pmid:1', {i for v in r.values() for i in v})   # gateway exclusion line is not a decision
        self.assertNotIn('pmid:6', json.dumps(x)); self.assertNotIn('pmid:7', json.dumps(x))   # verifier pool left out

    def test_marks(self):
        make(self.d)
        m = PR.exclusion_marks(self.d, {'pmid:1', 'pmid:2', 'pmid:3', 'pmid:5', 'pmid:9'})
        self.assertIn('two patients', m['pmid:5']); self.assertNotIn('pmid:9', m); self.assertNotIn('pmid:1', m)
        self.assertEqual(PR.norm_id('arXiv:2401.01234v3'), 'arxiv:2401.01234'); self.assertEqual(PR.norm_id('https://doi.org/10.1/AB'), 'doi:10.1/ab')

    def test_not_recorded(self):
        make(self.d, journal=False, result=False); x = PR.build(self.d)
        self.assertIsNone(x['identification']); self.assertEqual(x['included']['studies'], PR.NR)
        md = PR.markdown(x)
        self.assertIn('Records identified: not recorded', md); self.assertIn('Studies included in review: not recorded', md)
        self.assertIn('Reports of included studies (n = 2)', md)
        self.assertNotRegex(md, r'Records screened \(n = ')

    def test_outputs_and_svg(self):
        make(self.d)
        with contextlib.redirect_stdout(io.StringIO()) as o: c = PR.main([str(self.d)])
        self.assertEqual(c, 0)
        for f in ('PRISMA.md', 'PRISMA.svg', 'prisma.json'): self.assertTrue((self.d / f).is_file()); self.assertIn(f, o.getvalue())
        s = (self.d / 'PRISMA.svg').read_text()
        root = ET.fromstring(s); self.assertTrue(root.tag.endswith('svg'))
        self.assertNotIn('<i>', s); self.assertIn('case report &lt;i&gt;', s)
        self.assertNotIn('href', s)
        md = (self.d / 'PRISMA.md').read_text()
        for box in ('Records identified (n = 15)', 'duplicate records: n = 2', 'Records screened (n = 8)', 'Reports not retrieved (n = 2)',
                    'Reports assessed for eligibility (n = 4)', 'Reports excluded (n = 3)', 'Studies included in review (n = 1)', 'marked ineligible by automation tools: not recorded'):
            self.assertIn(box, md)
        with contextlib.redirect_stderr(io.StringIO()): self.assertEqual(PR.main([str(self.tmp / 'nope')]), 2)

    def test_finish_and_export_option(self):
        d = self.tmp / 'fr'; shutil.copytree(P / 'fixtures' / 'finish_run', d)
        fetch = F.gw.fetch; F.gw.fetch = lambda *a, **k: (_ for _ in ()).throw(OSError('offline test'))
        try:
            r = F.finish(d, offline=True)
            self.assertNotIn('prisma', [s['step'] for s in r['steps']]); self.assertFalse((d / 'PRISMA.svg').exists())
            self.assertNotIn('PRISMA 2020', (d / 'REPORT.html').read_text())
            r = F.finish(d, offline=True, prisma=True)
            st = {s['step']: s['status'] for s in r['steps']}
            self.assertEqual(st['prisma'], 'ok'); self.assertTrue(r['validation_passed'])
            self.assertTrue((d / 'PRISMA.svg').is_file()); self.assertIn(str((d / 'PRISMA.md').resolve()), r['files'])
            h = (d / 'REPORT.html').read_text()
            self.assertIn('PRISMA 2020 flow diagram', h); self.assertIn('<svg', h); self.assertIn('href="#prisma"', h)
        finally:
            F.gw.fetch = fetch
        self.assertEqual(ER.extras(d), [])


if __name__ == '__main__':
    unittest.main()
