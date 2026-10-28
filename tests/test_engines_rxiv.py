#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline tests of the preprint engines (v0.4.2): biorxiv, medrxiv (Europe PMC words restricted to the server, versions dated on api.biorxiv.org).
Visible before T; v1 on/after T refused; v1 before T and v2 on/after T -> v1 served, later_versions_masked; published link after T hidden;
forbidden DOI (preprint or published article) and title (any version); no date; not on the server; provider-side filter on the eve of T;
read routing (biorxiv:, medrxiv:, doi: of a preprint); host failure -> typed error; no key nor e-mail in URLs. Transport replaced (gateway.fetch).
Run: python3 -I tests/test_engines_rxiv.py"""
import json, os, pathlib, sys, tempfile, unittest, urllib.error, urllib.parse
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import gateway as gw   # noqa: E702

T = '2024-06-15'; V, F, D = '2024-06-14', '2024-06-16', '2024-06-15'
FORBIDDEN = ['10.1101/2024.01.05.000005', '10.9/forbidden-article']; FORBIDDEN_TITLE = 'A forbidden systematic review of everything that matters here'
KEYS = ('NCBI_API_KEY', 'OPENALEX_KEY', 'VP_CONTACT', 'HOME')
doi = lambda k: f'10.1101/2024.01.{k:02d}.{k:06d}'
# key -> versions [(date, title, abstract)], published DOI, EPMC dates (pub, index)
REC = {1: ([('2024-01-02', 'Alpha one', 'ABS-A1'), ('2024-03-01', 'Alpha two', 'ABS-A2')], '10.1/pub-ok', ('2024-01-02', '2024-01-03')),
       2: ([(F, 'Bravo', 'ABS-B')], None, ('2024-01-02', '2024-01-03')),                       # v1 after T (Europe PMC dates wrong): refused
       3: ([('2024-02-01', 'Charlie v1', 'ABS-C1'), (F, 'Charlie v2 rewritten', 'ABS-C2')], None, ('2024-02-01', '2024-02-02')),
       4: ([('2024-02-01', 'Delta', 'ABS-D')], '10.1/pub-late', ('2024-02-01', '2024-02-02')),  # published after T: link hidden
       5: ([('2024-02-01', 'Echo', 'ABS-E')], None, ('2024-02-01', '2024-02-02')),             # forbidden preprint DOI
       6: ([('2024-02-01', 'Foxtrot', 'ABS-F')], '10.9/forbidden-article', ('2024-02-01', '2024-02-02')),   # published = forbidden article
       7: ([('2024-02-01', 'Golf', 'ABS-G'), (F, FORBIDDEN_TITLE, 'ABS-G2')], None, ('2024-02-01', '2024-02-02')),   # forbidden title, later version
       8: ([(None, 'Hotel', 'ABS-H')], None, ('2024-02-01', '2024-02-02')),                     # no date on the server
       9: ([('2024-02-01', 'India', 'ABS-I')], None, ('2024-02-01', None)),                     # no Europe PMC indexing date
       10: ([], None, ('2024-02-01', '2024-02-02')),                                             # not on the server
       11: ([(D, 'Kilo', 'ABS-K')], None, ('2024-02-01', '2024-02-02'))}                        # v1 on day T
CROSSREF = {'10.1/pub-ok': ('2024-04-01', '2024-04-10'), '10.1/pub-late': (F, F)}


def hit(k, server='bioRxiv'):
    return {'id': f'PPR{k}', 'source': 'PPR', 'doi': doi(k), 'title': REC[k][0][0][1] if REC[k][0] else 'x', 'pubType': 'preprint',
            'bookOrReportDetails': {'publisher': server}, 'firstPublicationDate': REC[k][2][0], 'firstIndexDate': REC[k][2][1]}


def details(k, server):
    vs, pub, _ = REC[k]
    if not vs: return {'messages': [{'status': 'no posts found'}], 'collection': []}
    return {'messages': [{'status': 'ok'}], 'collection': [{'doi': doi(k), 'version': str(i + 1), 'date': d, 'title': t, 'abstract': a, 'authors': 'Doe, J.; Roe, R.',
                                                            'category': 'immunology', 'license': 'cc_by', 'published': pub or 'NA', 'server': server}
                                                           for i, (d, t, a) in reversed(list(enumerate(vs)))]}   # server order not trusted


class Rxiv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)
        self.env = {k: os.environ.pop(k) for k in KEYS if k in os.environ}; os.environ['HOME'] = str(self.d / 'home')
        self.saved = (gw.fetch, gw.STATE); gw.STATE = self.d / 'state'; self.urls = []; self.down = False
        self.hits = [hit(k) for k in REC] + [dict(hit(1), id='PPR1b'), {'id': 'PPR99', 'title': 'no doi', 'firstPublicationDate': '2024-01-01', 'firstIndexDate': '2024-01-02'}]
        gw.fetch = self.fake

    def tearDown(self):
        gw.fetch, gw.STATE = self.saved
        for k in KEYS: os.environ.pop(k, None)
        os.environ.update(self.env); self.tmp.cleanup()

    def fake(self, url, headers=None):
        self.urls.append(url)
        if url.startswith('https://www.ebi.ac.uk/europepmc/webservices/rest/search'):
            return json.dumps({'hitCount': 1234, 'resultList': {'result': self.hits}}).encode()
        if url.startswith(gw.RXIV):
            if self.down: raise urllib.error.HTTPError(url, 503, 'down', {}, None)
            server, rest = url[len(gw.RXIV):].split('/', 1); d_ = rest.rsplit('/na/json', 1)[0]
            k = next((k for k in REC if doi(k) == d_), None)
            return json.dumps(details(k, server) if k and server == 'biorxiv' else {'messages': [{'status': 'no posts found'}], 'collection': []}).encode()
        if url.startswith('https://api.crossref.org/works?'):
            f = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['filter'][0]
            items = [{'DOI': x, 'title': ['Article ' + x], 'container-title': ['J Test'], 'issued': {'date-parts': [[int(p) for p in CROSSREF[x][0].split('-')]]},
                      'created': {'date-time': CROSSREF[x][1] + 'T00:00:00Z'}} for x in (y[4:] for y in f.split(',')) if x in CROSSREF]
            return json.dumps({'message': {'items': items, 'total-results': len(items)}}).encode()
        raise AssertionError('unexpected URL ' + url)

    def B(self): return gw.Barrier(T, FORBIDDEN, [FORBIDDEN_TITLE])

    def clean(self):
        for u in self.urls:
            v = urllib.parse.unquote(u); self.assertNotIn('@', v); self.assertNotIn('api_key', v); self.assertNotIn('mailto', v); self.assertNotIn('key=', v)

    def test_search_barrier(self):
        B = self.B(); out, total = gw.search_biorxiv('spike antibody', 20, B)
        self.assertEqual([x['id'] for x in out], ['doi:' + doi(k) for k in (1, 3, 4)]); self.assertEqual(total, 1234)
        self.assertEqual(B.excluded, 9)                                    # 2, 5, 6, 7, 8, 9, 10, 11, no DOI (the duplicate of 1 is skipped)
        a, c, d_ = out
        self.assertEqual((a['version'], a['date'], a['date_version'], a['title'], a['later_versions_masked']), ('2', '2024-01-02', '2024-03-01', 'Alpha two', False))
        self.assertEqual((a['published_doi'], a['published_journal'], a['published_year']), ('10.1/pub-ok', 'J Test', '2024'))
        self.assertEqual((c['version'], c['title'], c['later_versions_masked'], c['date_version']), ('1', 'Charlie v1', True, '2024-02-01'))
        self.assertIsNone(d_['published_doi']); self.assertNotIn('published_journal', d_)
        for x in out:
            self.assertEqual((x['server'], x['type'], x['peer_review']), ('bioRxiv', 'preprint', 'not peer reviewed (preprint)')); self.assertNotIn('_pub', x)
            self.assertNotIn(F, json.dumps(x)); self.assertNotIn(D, json.dumps(x)); self.assertNotIn('abstract', x)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.urls[0]).query)['query'][0]
        self.assertEqual(q, '(spike antibody) AND SRC:PPR AND PUBLISHER:"bioRxiv" AND FIRST_PDATE:[1800-01-01 TO 2024-06-14] AND FIRST_IDATE:[1800-01-01 TO 2024-06-14]')
        self.assertEqual(sum(u.startswith(gw.RXIV) for u in self.urls), 11)  # one per distinct preprint DOI
        self.assertTrue(all(u.startswith(gw.RXIV + 'biorxiv/') for u in self.urls if u.startswith(gw.RXIV))); self.clean()

    def test_since_and_medrxiv_filter(self):
        B = gw.Barrier(T, since=2020); self.hits = []
        self.assertEqual(gw.search_medrxiv('x', 5, B), ([], 1234))
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.urls[0]).query)['query'][0]
        self.assertIn('PUBLISHER:"medRxiv" AND FIRST_PDATE:[2020-01-01 TO 2024-06-14] AND FIRST_IDATE:[2020-01-01 TO 2024-06-14]', q)

    def test_read(self):
        r = gw.read('biorxiv:' + doi(3), self.B())
        self.assertEqual((r['id'], r['abstract'], r['version'], r['later_versions_masked']), ('doi:' + doi(3), 'ABS-C1', '1', True))
        r = gw.read('doi:' + doi(1) + 'v2', self.B()); self.assertEqual((r['abstract'], r['published_doi']), ('ABS-A2', '10.1/pub-ok'))
        self.assertFalse(any('europepmc' in u for u in self.urls))         # a preprint DOI never reaches the Europe PMC core record (latest version)
        r = gw.read(doi(4), self.B()); self.assertEqual((r['abstract'], r['published_doi']), ('ABS-D', None))
        for k in (2, 5, 6, 7, 8, 11): self.assertIn('refusal', gw.read('biorxiv:' + doi(k), self.B()), k)
        self.assertEqual(gw.read('medrxiv:' + doi(1), self.B()), {'refusal': 'not found on api.biorxiv.org'})
        self.assertIn('expected form', gw.read('biorxiv:10.1101/gad.1234', self.B())['refusal'])
        self.assertIsNone(gw.rxiv_ident('doi:10.1101/gad.123456.120')); self.assertIsNone(gw.rxiv_ident('pmid:123'))
        self.assertEqual(gw.rxiv_ident('doi:10.64898/2026.10.26.26366210'), (None, '10.64898/2026.10.26.26366210'))
        self.clean()

    def test_chaining_gate(self):
        self.assertEqual(gw.citing('biorxiv:' + doi(2), 10, self.B()), ([], 'document after T, forbidden or not found'))
        self.assertEqual(gw.references('doi:' + doi(7), 10, self.B()), ([], 'document after T, forbidden or not found'))
        self.assertTrue(all(u.startswith(gw.RXIV) for u in self.urls))

    def test_host_down(self):
        self.down = True
        with self.assertRaises(gw.ProviderError) as e: gw.search_biorxiv('x', 20, self.B())
        self.assertIn('not an empty result', str(e.exception)); self.assertEqual(sum(u.startswith(gw.RXIV) for u in self.urls), 1)   # stops at the first failure

    def test_gateway_declared(self):
        p = self.d / 'p.md'; p.write_text('# p\n```sources\nengines: biorxiv, medrxiv\ncap: 9\n```\n', encoding='utf-8')
        g = gw.Gateway([str(p)], T=T, state=str(self.d / 'st'))
        self.assertEqual(g.sources()['engines'], ['biorxiv', 'medrxiv'])
        r = g.call('search-biorxiv', 'spike'); self.assertEqual(len(r['results']), 6); self.assertEqual(r['engine'], 'biorxiv')   # no forbidden list here: 1, 3, 4, 5, 6, 7
        q = self.d / 'q.md'; q.write_text('# q\n```sources\nengines: pubmed\n```\n', encoding='utf-8')
        self.assertIn('refusal', gw.Gateway([str(q)], T=T, state=str(self.d / 'st2')).call('search-biorxiv', 'spike'))


if __name__ == '__main__':
    unittest.main()
