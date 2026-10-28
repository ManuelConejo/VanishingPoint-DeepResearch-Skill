#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline tests of tools/verifier/fetch_fulltext.py (v0.4.4): full text pinned before T. arXiv: last version submitted before T
(OAI-PMH arXivRaw dates; a version on day T is excluded; explicit vN = ceiling), only that version's URLs requested; no version before T
-> REFUSED, nothing downloaded. bioRxiv/medRxiv: last version posted before T named, www.biorxiv.org / www.medrxiv.org never called, no
fallback to Europe PMC or Unpaywall. No T -> REFUSED without any request, stale copy deleted. Europe PMC: full text only when first
published before T, flagged as possibly corrected later. Unpaywall: arXiv copies pinned, publisher copy dated by the article.
verifier.load_sources: a copy fetched for another T is not read; --fulltext without T refused. Transport replaced (fetch_fulltext.get).
Run: python3 -I tests/test_fetch_fulltext.py"""
import contextlib, io, json, os, pathlib, sys, tempfile, unittest, urllib.parse
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools' / 'verifier')); sys.path.insert(0, str(P.parent / 'tools'))
import fetch_fulltext as F   # noqa: E402
import verifier as V         # noqa: E402

AX = {'1706.03762': ['Mon, 12 Jun 2017 17:57:34 GMT', 'Mon, 19 Jun 2017 16:49:45 GMT', 'Wed, 02 Aug 2023 00:41:18 GMT'],
      'hep-th/9901001': ['Fri, 01 Jan 1999 10:00:00 GMT']}
RX = {'10.1101/2020.03.22.002386': ['2020-03-22', '2020-03-23', '2020-03-27']}
EPMC = {'PMC1': '2020-01-10', 'PMC2': '2020-03-25', 'PMC3': None}
OAI = ('<?xml version="1.0"?><OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><GetRecord><record><metadata>'
       '<arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/"><id>{id}</id>{v}</arXivRaw></metadata></record></GetRecord></OAI-PMH>')


class FetchFulltext(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.out = pathlib.Path(self.tmp.name) / 'S1'; self.out.mkdir()
        self.saved = (F.get, F.T, F.PDF_ONLY, F.CONTACT); self.urls = []; self.unpaywall = None
        F.get = self.fake; F.CONTACT = ''

    def tearDown(self):
        F.get, F.T, F.PDF_ONLY, F.CONTACT = self.saved; self.tmp.cleanup()

    def fake(self, url, accept=None):
        self.urls.append(url); u = urllib.parse.urlsplit(url); q = urllib.parse.parse_qs(u.query)
        if u.hostname == 'oaipmh.arxiv.org':
            i = q['identifier'][0].split(':', 2)[2]
            if i not in AX: return 200, 'text/xml', b'<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><error code="idDoesNotExist"/></OAI-PMH>', url
            v = ''.join(f'<version version="v{n + 1}"><date>{d}</date></version>' for n, d in enumerate(AX[i]))
            return 200, 'text/xml', OAI.format(id=i, v=v).encode(), url
        if u.hostname == 'arxiv.org':
            if u.path.startswith('/html/'): return 200, 'text/html', ('<p>' + 'TEXT OF ' + u.path[6:] + ' ' * 10 + '</p>') .encode() * 300, url
            return 404, '', b'', url
        if u.hostname == 'api.biorxiv.org':
            server, doi = u.path.split('/', 3)[2], u.path.split('/', 3)[3].rsplit('/na/json', 1)[0]
            vs = RX.get(doi) if server == 'biorxiv' else None
            coll = [{'doi': doi, 'version': str(n + 1), 'date': d} for n, d in reversed(list(enumerate(vs or [])))]
            return 200, 'application/json', json.dumps({'messages': [{'status': 'ok' if vs else 'no posts found'}], 'collection': coll}).encode(), url
        if url.startswith('https://www.ebi.ac.uk/europepmc/webservices/rest/search'):
            k = q['query'][0].split(':', 1)[1].strip('"'); k = {'10.1/pub': 'PMC1', '10.1/late': 'PMC2'}.get(k, k)
            res = [{'pmcid': k, 'isOpenAccess': 'Y', 'firstPublicationDate': EPMC[k]}] if k in EPMC else []
            return 200, 'application/json', json.dumps({'resultList': {'result': res}}).encode(), url
        if url.endswith('/fullTextXML'): return 200, 'text/xml', b'<article><p>' + b'FULL TEXT XML ' * 400 + b'</p></article>', url
        if u.hostname == 'api.unpaywall.org': return 200, 'application/json', json.dumps(self.unpaywall).encode(), url
        if u.hostname == 'publisher.example': return 200, 'application/pdf', b'%PDF-1.4 publisher', url
        raise AssertionError('unexpected URL ' + url)

    def run_main(self, *args):
        argv = sys.argv; sys.argv = ['fetch_fulltext.py', *args, '--out', str(self.out)]
        try:
            with contextlib.redirect_stdout(io.StringIO()): F.main()
        finally: sys.argv = argv
        return json.loads((self.out / 'meta.json').read_text())

    def text(self): return (self.out / 'source.txt').read_text() if (self.out / 'source.txt').exists() else None

    def test_arxiv_last_version_before_T(self):
        m = self.run_main('--arxiv', '1706.03762', '--T', '2017-06-15')
        self.assertEqual((m['status'], m['version'], m['version_date'], m['later_versions_masked'], m['versions_total']), ('OK', 'v1', '2017-06-12', True, 3))
        self.assertIn('TEXT OF 1706.03762v1', self.text())
        content = [u for u in self.urls if urllib.parse.urlsplit(u).hostname == 'arxiv.org']
        self.assertTrue(content); self.assertTrue(all(u.endswith('/1706.03762v1') for u in content))     # only that version
        self.assertEqual(self.run_main('--arxiv', '1706.03762', '--T', '2017-06-19')['version'], 'v1')    # v2 on day T: excluded
        self.assertEqual(self.run_main('--arxiv', 'arXiv:1706.03762', '--T', '2017-06-20')['version'], 'v2')
        m = self.run_main('--arxiv', '1706.03762v2', '--T', '2026-01-01')                                 # explicit version = ceiling
        self.assertEqual((m['version'], m['later_versions_masked']), ('v2', True))
        self.assertEqual(self.run_main('--arxiv', 'hep-th/9901001', '--T', '2000-01-01')['version'], 'v1')
        self.assertEqual(self.run_main('--doi', '10.48550/arXiv.1706.03762', '--T', '2017-06-15')['version'], 'v1')

    def test_arxiv_no_version_before_T(self):
        self.run_main('--arxiv', '1706.03762', '--T', '2017-06-15'); self.urls.clear()            # a copy exists for another T
        m = self.run_main('--arxiv', '1706.03762', '--T', '2017-06-12')                            # v1 on day T
        self.assertEqual(m['status'], 'REFUSED'); self.assertIn('before T', m['reason']); self.assertIsNone(self.text())
        self.assertFalse([u for u in self.urls if urllib.parse.urlsplit(u).hostname == 'arxiv.org'])
        self.assertEqual(self.run_main('--arxiv', '9999.99999', '--T', '2020-01-01')['status'], 'SOURCE-UNAVAILABLE')

    def test_biorxiv_version_named_never_www(self):
        F.CONTACT = 'team@example.org'; self.unpaywall = {'best_oa_location': {'url_for_pdf': 'https://www.biorxiv.org/x.pdf'}}
        m = self.run_main('--doi', '10.1101/2020.03.22.002386', '--T', '2020-03-25')
        self.assertEqual((m['status'], m['version'], m['version_date'], m['later_versions_masked']), ('SOURCE-UNAVAILABLE', 'v2', '2020-03-23', True))
        self.assertIn('v2 (2020-03-23)', m['reason']); self.assertIsNone(self.text())
        self.assertEqual({urllib.parse.urlsplit(u).hostname for u in self.urls}, {'api.biorxiv.org'})   # no www, no Europe PMC, no Unpaywall
        self.assertNotIn('medrxiv', ' '.join(self.urls).replace('api.biorxiv.org/details/biorxiv', ''))
        m = self.run_main('--doi', '10.1101/2020.03.22.002386v3', '--T', '2020-03-22')
        self.assertEqual(m['status'], 'REFUSED'); self.assertIn('2020-03-22', m['reason'])

    def test_no_T_refused_without_request(self):
        (self.out / 'source.txt').write_text('latest version, fetched before the T rule'); (self.out / 'meta.json').write_text('{"status": "OK"}')
        for args in (('--arxiv', '1706.03762'), ('--doi', '10.1/pub'), ('--pmcid', 'PMC1'), ('--arxiv', '1706.03762', '--T', 'soon')):
            m = self.run_main(*args)
            self.assertEqual(m['status'], 'REFUSED'); self.assertIn('no valid date T', m['reason'])
        self.assertEqual(self.urls, []); self.assertIsNone(self.text())

    def test_europepmc_first_publication_before_T(self):
        m = self.run_main('--pmcid', 'PMC1', '--T', '2020-02-01')
        self.assertEqual((m['status'], m['first_publication_date']), ('OK', '2020-01-10')); self.assertIn('corrections', m['warning'])
        self.assertIn('FULL TEXT XML', self.text())
        self.urls.clear(); m = self.run_main('--pmcid', 'PMC2', '--T', '2020-03-25')                 # first published on day T
        self.assertEqual(m['status'], 'REFUSED'); self.assertFalse([u for u in self.urls if u.endswith('fullTextXML')]); self.assertIsNone(self.text())
        self.assertEqual(self.run_main('--pmcid', 'PMC3', '--T', '2020-03-25')['status'], 'REFUSED')   # no date: refused
        m = self.run_main('--doi', '10.1/pub', '--T', '2020-02-01'); self.assertEqual((m['status'], m['method']), ('OK', 'europepmc-xml'))
        self.assertEqual(self.run_main('--doi', '10.1/late', '--T', '2020-02-01')['status'], 'REFUSED')
        F.T = F.dt.date(2020, 3, 1)                                                                   # partial dates: upper bound of the period
        self.assertEqual([F.before_T(x) for x in ('2019', '2020-02', '2020-03', '2020', '2020-02-29T23:00', None, 'n.d.')], [True, True, False, False, True, False, False])

    def test_unpaywall_pinned_and_dated(self):
        F.CONTACT = 'team@example.org'
        self.unpaywall = {'published_date': '2017-12-01', 'best_oa_location': {'url_for_pdf': 'https://arxiv.org/pdf/1706.03762', 'version': 'submittedVersion'},
                          'oa_locations': [{'url_for_pdf': 'https://publisher.example/a.pdf', 'version': 'publishedVersion'}]}
        m = self.run_main('--doi', '10.9/journal', '--T', '2017-06-15')                               # journal after T, arXiv v1 before T
        self.assertEqual((m['status'], m['version']), ('OK', 'v1')); self.assertNotIn('https://arxiv.org/pdf/1706.03762', self.urls)
        self.unpaywall['best_oa_location']['url_for_pdf'] = 'https://arxiv.org/pdf/0000.00000'; AX['0000.00000'] = ['Tue, 01 Jan 2019 00:00:00 GMT']
        (self.out / 'meta.json').unlink(); self.urls.clear(); m = self.run_main('--doi', '10.9/journal', '--T', '2017-06-15')
        self.assertEqual(m['status'], 'REFUSED'); self.assertNotIn('publisher.example', ' '.join(self.urls))
        m = self.run_main('--doi', '10.9/journal', '--T', '2018-06-01')                               # published before T, arXiv copy after
        self.assertEqual((m['status'], m['method'], m['oa_version']), ('OK-PDF', 'unpaywall-pdf', 'publishedVersion')); self.assertIn('warning', m)
        self.assertNotIn('https://arxiv.org/pdf/0000.00000', self.urls)                               # never fetched unpinned

    def test_verifier_reads_only_copies_for_its_T(self):
        card = {'sources': {'S1': {'arxiv': '1706.03762'}}, 'claims': [{'id': 'A1', 'text': 'x', 'source': {'key': 'S1'}}]}
        (self.out / 'source.txt').write_text('copy for T1'); (self.out / 'meta.json').write_text(json.dumps({'status': 'OK', 'T': '2017-06-15', 'T_rule': 'x'}))
        d = self.out.parent
        self.assertEqual(V.load_sources(card, d, T='2017-06-15')['S1']['origin'], 'fulltext')
        self.assertEqual(V.load_sources(card, d, T='2017-06-20')['S1']['origin'], 'missing')         # another T: not read back
        (self.out / 'meta.json').write_text('{"status": "OK"}')
        self.assertEqual(V.load_sources(card, d, T='2017-06-15')['S1']['origin'], 'missing')         # fetched before the T rule
        s = V.load_sources(card, d, fulltext=True, out_dir=d)['S1']
        self.assertEqual((s['origin'], s['note']), ('missing', 'full text refused: no T (abstract only)'))


if __name__ == '__main__':
    unittest.main()
