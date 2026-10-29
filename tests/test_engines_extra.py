#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline tests of the extra keyless engines (v0.3.1): clinicaltrials (biology), dblp (cs-ai), econbiz (finance), osv (code engine `vulns`),
of the Software Heritage token (SWH_TOKEN sent as Bearer to archive.softwareheritage.org only) and of the invalid-key fallback
(NCBI 400 "API key invalid", OpenAlex 401/403, SWH 401/403 -> one retry without the key, key-less for the rest of the run, flag key_invalid).
Per engine: a record before T (the only visible one), after T, on day T, partial date at T's year, forbidden DOI or identifier, forbidden
title, no date; the provider-side filter on the eve of T in the URL (or none for OSV: no date filter in its API); no key nor e-mail in URLs.
Transport replaced (gateway.fetch, CodeClient._send, urllib.request.urlopen): no network.
Run: python3 -I tests/test_engines_extra.py"""
import datetime as dt, email, io, json, os, pathlib, sys, tempfile, unittest, urllib.error, urllib.parse, urllib.request, urllib.response
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import gateway as gw, code_sources as sc, check_keys as ck   # noqa: E702

T = '2024-06-15'; V, F, D = '2024-06-14', '2024-06-16', '2024-06-15'           # before (eve), after, day T
FORBIDDEN_DOI, FORBIDDEN_TITLE = '10.9/forbidden', 'A forbidden systematic review of everything that matters here'
FAKE = 'FAKE-KEY-NOT-A-SECRET-0123456789'
KEYS = ('NCBI_API_KEY', 'OPENALEX_KEY', 'SWH_TOKEN', 'VP_GITHUB_TOKEN', 'VP_CONTACT', 'HOME')


def barrier(): return gw.Barrier(T, [FORBIDDEN_DOI], [FORBIDDEN_TITLE])


def crossref_answer(url, table):
    """Crossref batch filter=doi:a,doi:b answered from table {doi: (issued, created)}."""
    f = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['filter'][0]
    dois = [x[4:] for x in f.split(',') if x.startswith('doi:')]
    items = [{'DOI': d, 'title': ['x'], 'issued': {'date-parts': [[int(p) for p in table[d][0].split('-')]]}, 'created': {'date-time': table[d][1] + 'T00:00:00Z'}}
             for d in dois if d in table]
    return json.dumps({'message': {'items': items, 'total-results': len(items)}}).encode()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)
        self.env = {k: os.environ.pop(k) for k in KEYS if k in os.environ}
        os.environ['HOME'] = str(self.d / 'home')                                # never the real ~/.config/vp
        self.saved = (gw.fetch, gw.STATE, urllib.request.urlopen, gw.time.sleep)
        gw.STATE = self.d / 'state'; self.urls = []

    def tearDown(self):
        gw.fetch, gw.STATE, urllib.request.urlopen, gw.time.sleep = self.saved
        for k in KEYS: os.environ.pop(k, None)
        os.environ.update(self.env); self.tmp.cleanup()

    def plugin(self, engines, name='p'):
        p = self.d / f'{name}.md'
        p.write_text(f'# {name}\n## Sources\n```sources\nengines: {engines}\ncap: 50\n```\n', encoding='utf-8'); return p

    def clean_urls(self):
        for u in self.urls:
            self.assertNotIn(FAKE, u); self.assertNotIn('@', urllib.parse.unquote(u)); self.assertNotIn('api_key', u); self.assertNotIn('mailto', u)


class ClinicalTrials(Base):
    def study(self, nct, title, submit, post, last=V, results=None):
        st = {'overallStatus': 'COMPLETED', 'studyFirstSubmitDate': submit, 'lastUpdatePostDateStruct': {'date': last}, 'startDateStruct': {'date': '2020-01'}}
        if post: st['studyFirstPostDateStruct'] = {'date': post}
        if results: st['resultsFirstPostDateStruct'] = {'date': results}
        return {'protocolSection': {'identificationModule': {'nctId': nct, 'briefTitle': title}, 'statusModule': st,
                                    'designModule': {'studyType': 'INTERVENTIONAL', 'phases': ['PHASE3'], 'enrollmentInfo': {'count': 100}},
                                    'conditionsModule': {'conditions': ['Obesity']}, 'descriptionModule': {'briefSummary': 'SUMMARY'},
                                    'outcomesModule': {'primaryOutcomes': [{'measure': 'Weight', 'timeFrame': '68 weeks'}]}}, 'hasResults': bool(results)}

    def fixtures(self):
        return [self.study('NCT00000001', 'Old trial', '2020-01-01', V), self.study('NCT00000002', 'After', V, F),
                self.study('NCT00000003', 'Day T', V, D), self.study('NCT00000004', 'Partial', '2024', '2024'),
                self.study('NCT00000005', FORBIDDEN_TITLE, V, V), self.study('NCT00000006', 'Forbidden id', V, V),
                self.study('NCT00000007', 'No date', None, None), self.study('NCT00000008', 'Late submit', F, V)]

    def test_search_barrier_and_provider_filter(self):
        studies = self.fixtures()
        gw.fetch = lambda url, headers=None: self.urls.append(url) or json.dumps({'studies': studies, 'totalCount': 8}).encode()
        os.environ.update(NCBI_API_KEY=FAKE, OPENALEX_KEY=FAKE)
        B = gw.Barrier(T, [FORBIDDEN_DOI, 'NCT00000006'], [FORBIDDEN_TITLE])
        out, total = gw.search_clinicaltrials('semaglutide', 10, B)
        self.assertEqual([x['id'] for x in out], ['nct:NCT00000001']); self.assertEqual((B.excluded, total), (7, 8))
        self.assertIn('filter.advanced=AREA[StudyFirstPostDate]RANGE[MIN,2024-06-14]', urllib.parse.unquote(self.urls[0]))
        self.assertTrue(self.urls[0].startswith('https://clinicaltrials.gov/api/v2/studies?')); self.clean_urls()
        x = out[0]
        self.assertEqual((x['status'], x['phase'], x['enrollment'], x['conditions'], x['validity']), ('COMPLETED', ['PHASE3'], 100, ['Obesity'], 'record unchanged since before T'))

    def test_record_updated_after_T_is_masked_and_results_dated(self):
        B = barrier()
        x = gw.ct_item(self.study('NCT00000011', 'Old trial', '2020-01-01', '2020-01-02', last=F, results=F), B, with_text=True)
        self.assertEqual((x['status'], x['phase'], x['enrollment'], x['start_date'], x['date_last_update']), (None, None, None, None, None))
        self.assertEqual((x['has_results'], x['date_results_posted'], x['primary_outcomes']), (False, None, None))
        self.assertIn('masked', x['abstract']); self.assertIn('updated on/after T', x['validity'])
        y = gw.ct_item(self.study('NCT00000012', 'Old trial', '2020-01-01', '2020-01-02', last=V, results='2023-01-01'), B, with_text=True)
        self.assertEqual((y['has_results'], y['date_results_posted'], y['abstract'], y['primary_outcomes'][0]['measure']), (True, '2023-01-01', 'SUMMARY', 'Weight'))

    def test_read_nct(self):
        gw.fetch = lambda url, headers=None: self.urls.append(url) or json.dumps(self.study('NCT01234567', 'Old', '2020-01-01', V)).encode()
        r = gw.read('nct:NCT01234567', barrier())
        self.assertEqual((r['id'], r['abstract']), ('nct:NCT01234567', 'SUMMARY')); self.assertEqual(self.urls, ['https://clinicaltrials.gov/api/v2/studies/NCT01234567'])
        gw.fetch = lambda url, headers=None: json.dumps(self.study('NCT01234567', 'New', V, F)).encode()
        self.assertIn('refusal', gw.read('nct:NCT01234567', barrier()))
        self.assertIn('refusal', gw.read('nct:../x', barrier()))
        self.assertEqual(gw.citing('nct:NCT01234567', 5, barrier())[0], [])


class Dblp(Base):
    ROWS = [('conf/a/Old23', 'Old paper', '2023', None, '10.1/old'), ('conf/a/After25', 'After', '2025', None, None),
            ('conf/a/DayT24', 'Same year as T', '2024', None, None), ('conf/a/Event', 'Event year at T', '2023', '2024', None),
            ('conf/a/Forb', 'Forbidden DOI', '2020', None, FORBIDDEN_DOI), ('conf/a/FT', FORBIDDEN_TITLE, '2020', None, None),
            ('conf/a/NoDate', 'No date', None, None, None), ('conf/a/LateDeposit', 'Late deposit', '2022', None, '10.1/late'),
            ('conf/a/NoCrossref', 'DOI absent from Crossref', '2022', None, '10.1/absent'), ('journals/corr/abs-2405-00001', 'CoRR May', '2024', None, '10.48550/arXiv.2405.00001'),
            ('journals/corr/abs-2406-00001', 'CoRR June', '2024', None, '10.48550/arXiv.2406.00001'), ('conf/a/NoDoi22', 'Old without DOI', '2022', None, None)]

    def fetch(self, url, headers=None):
        self.urls.append(url)
        if 'sparql.dblp.org' in url:
            self.assertEqual(headers, {'Accept': 'application/sparql-results+json'})
            b = [{k: {'value': v} for k, v in (('p', 'https://dblp.org/rec/' + p), ('title', t), ('year', y), ('ev', e), ('doi', d and 'https://doi.org/' + d),
                                                ('label', 'A. Author et al.: ' + t)) if v} for p, t, y, e, d in self.ROWS]
            return json.dumps({'results': {'bindings': b}}).encode()
        return crossref_answer(url, {'10.1/old': ('2023-01-01', '2023-01-02'), '10.1/late': ('2022-01-01', F)})

    def test_search_barrier_years_doi_recheck_and_provider_filter(self):
        gw.fetch = self.fetch; os.environ.update(NCBI_API_KEY=FAKE, OPENALEX_KEY=FAKE); B = barrier()
        out, note = gw.search_dblp('retrieval augmented', 20, B)
        self.assertEqual([x['id'] for x in out], ['doi:10.1/old', 'arxiv:2405.00001', 'dblp:conf/a/NoDoi22'])
        self.assertEqual(B.excluded, 10)                                                  # 9 records; a late Crossref deposit is counted twice (cr_item + crossref_deposit, existing rule)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.urls[0]).query)['query'][0]
        self.assertIn('FILTER(?year < "2024"^^xsd:gYear)', q); self.assertIn('ql:contains-word "retrieval"', q); self.assertIn('ql:contains-word "augmented"', q)
        self.assertTrue(self.urls[0].startswith('https://sparql.dblp.org/sparql?'))
        self.assertTrue(all('api.crossref.org' in u for u in self.urls[1:]) and len(self.urls) == 2); self.clean_urls()
        self.assertEqual(gw.search_dblp('a b', 5, barrier())[0], [])                       # no usable word: no call
        self.assertEqual(len(self.urls), 2)

    def test_errors_are_typed_never_empty(self):
        gw.fetch = lambda url, headers=None: b'<!doctype html><title>Making sure you are not a bot!</title>'
        with self.assertRaises(gw.ProviderError) as cm: gw.search_dblp('graph neural', 5, barrier())
        self.assertIn('bot_challenge', str(cm.exception))
        def r429(body, retry):
            def f(url, headers=None): raise urllib.error.HTTPError(url, 429, 'Too Many', email.message_from_string(f'Retry-After: {retry}\n' if retry else ''), io.BytesIO(body))
            return f
        gw.fetch = r429(b'', '30')
        with self.assertRaises(gw.ProviderError) as cm: gw.search_dblp('graph neural', 5, barrier())
        self.assertIn('rate_limited: dblp asks to wait 30 s', str(cm.exception))
        gw.fetch = r429(b'{"exception": "Operation timed out. Last operation: Filter"}', None)
        with self.assertRaises(gw.ProviderError) as cm: gw.search_dblp('graph neural', 5, barrier())
        self.assertIn('timed out', str(cm.exception))
        self.assertIn(429, gw.STOP['sparql.dblp.org']); self.assertGreaterEqual(gw.INTERVAL['sparql.dblp.org'], 1.0)

    def test_read_dblp_and_arxiv_month(self):
        self.ROWS = [('conf/acl/X24', 'Benchmarking', '2014', '2024', '10.1/old')]           # observed anomaly: publication 2014, event 2024
        gw.fetch = self.fetch
        r = gw.read('dblp:conf/acl/X24', gw.Barrier('2026-10-26'))
        self.assertEqual((r['id'], r['dblp'], r['year']), ('doi:10.1/old', 'conf/acl/X24', '2024'))
        self.assertIn('refusal', gw.read('dblp:conf/acl/X24', gw.Barrier('2019-06-01')))   # the event year counts too
        self.assertIn('refusal', gw.read('dblp:../../x', barrier()))
        self.assertEqual((gw.arxiv_month('2401.01234'), gw.arxiv_month('cs/9912001'), gw.arxiv_month('math.AG/0101001'), gw.arxiv_month('x')),
                         ('2024-01', '1999-12', '2001-01', None))


class EconBiz(Base):
    def hit(self, i, title, date, created, doi=None):
        h = {'id': str(10000000 + i), 'title': title, 'date': [date] if date else [], 'creator': ['Author, A.'], 'type': 'book'}
        if created: h['econbiz_created'] = created + 'T10:00:00Z'
        if doi: h['identifier_url'] = ['https://doi.org/' + doi, 'https://example.org/x']
        return h

    def fixtures(self):
        return [self.hit(1, 'Old', V, V), self.hit(2, 'After', F, V), self.hit(3, 'Day T', D, V), self.hit(4, 'Partial', '2024', '2023-01-01'),
                self.hit(5, 'Forbidden DOI', '2020', '2020-01-01', FORBIDDEN_DOI), self.hit(6, FORBIDDEN_TITLE, '2020', '2020-01-01'),
                self.hit(7, 'No date', None, None), self.hit(8, 'Indexed after T', '2020', F), self.hit(9, 'DOI before T', '6 May 2023', '2023-05-10', '10.1/old'),
                self.hit(10, 'DOI deposited after T', '2022', '2022-01-01', '10.1/late'), self.hit(1, 'Old', V, V)]

    def fetch(self, url, headers=None):
        self.urls.append(url)
        if 'api.econbiz.de' in url: return json.dumps({'hits': {'hits': self.fixtures(), 'total': 11}}).encode()
        return crossref_answer(url, {'10.1/old': ('2023-05-06', '2023-05-07'), '10.1/late': ('2022-01-01', F)})

    def test_search_barrier_doi_recheck_and_provider_filter(self):
        gw.fetch = self.fetch; os.environ.update(NCBI_API_KEY=FAKE, OPENALEX_KEY=FAKE); B = barrier()
        out, total = gw.search_econbiz('inflation expectations', 20, B)
        self.assertEqual([x['id'] for x in out], ['econbiz:10000001', 'doi:10.1/old']); self.assertEqual((B.excluded, total), (9, 11))   # 8 records, late deposit counted twice
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.urls[0]).query)['q'][0]
        self.assertEqual(q, '(inflation expectations) AND econbiz_created:[* TO 2024-06-14T23:59:59Z] AND date_sort:[* TO 2024]')
        self.assertTrue(self.urls[0].startswith('https://api.econbiz.de/v1/search?')); self.clean_urls()
        self.assertEqual((out[1]['date'], out[1]['date_indexed']), ('2023-05-06', '2023-05-10'))

    def test_free_text_dates(self):
        for s, want in (('2018-08-03', '2018-08-03'), ('6 May 2026', '2026-05-06'), ('27. April 2017', '2017-04-27'), ('January 2026', '2026-01'),
                        ('1st quarter 2026', '2026-03'), ('[2015]', '2015'), ('2019-09-26 - 2019-09-28', '2019-09-28'), ('Oktober 2020', '2020-10'),
                        ('n.d.', None), ('', None)):
            self.assertEqual(gw.econbiz_date(s), want, s)

    def test_read_econbiz(self):
        gw.fetch = lambda url, headers=None: self.urls.append(url) or json.dumps({'record': dict(self.hit(1, 'Old', '2020', '2020-02-02'), abstract=['An abstract.'])}).encode()
        r = gw.read('econbiz:10000001', barrier())
        self.assertEqual((r['id'], r['abstract']), ('econbiz:10000001', 'An abstract.')); self.assertEqual(self.urls, ['https://api.econbiz.de/v1/record/10000001'])
        gw.fetch = lambda url, headers=None: json.dumps({'record': self.hit(1, 'Old', '2020', F)}).encode()
        self.assertIn('refusal', gw.read('econbiz:10000001', barrier()))
        self.assertIn('refusal', gw.read('econbiz:1/../2', barrier()))


class Osv(Base):
    def vuln(self, vid, published, modified=V, summary='Sandbox escape', **kw):
        v = dict({'id': vid, 'aliases': ['CVE-0000-' + vid[-1]], 'summary': summary, 'details': 'DETAILS', 'modified': modified,
                  'affected': [{'package': {'name': 'p', 'ecosystem': 'PyPI'}, 'ranges': [{'events': [{'introduced': '0'}, {'fixed': '2.0'}]}]}],
                  'severity': [{'type': 'CVSS_V3', 'score': 'X'}], 'references': [{'url': 'https://example.org/a'}]}, **kw)
        if published: v['published'] = published
        return v

    def fixtures(self):
        return [self.vuln('GHSA-old1', V + 'T00:00:00Z'), self.vuln('GHSA-aft2', F + 'T00:00:00Z'), self.vuln('GHSA-day3', D + 'T00:00:00Z'),
                self.vuln('GHSA-par4', '2024'), self.vuln('GHSA-forb5', '2020-01-01T00:00:00Z'), self.vuln('GHSA-tit6', '2020-01-01T00:00:00Z', summary=FORBIDDEN_TITLE),
                self.vuln('GHSA-nod7', None)]

    def client(self, seen, answer):
        c = sc.CodeClient(cache_dir=self.d / 'state'); c.sleep = lambda s: None
        c._send = lambda url, headers, body=None: (seen.append((url, headers, body)) or (200, json.dumps(answer).encode()))
        return c

    def test_vulns_barrier_and_post_body(self):
        seen = []; os.environ.update(NCBI_API_KEY=FAKE, OPENALEX_KEY=FAKE, SWH_TOKEN=FAKE)
        B = gw.Barrier(T, [FORBIDDEN_DOI, 'GHSA-forb5'], [FORBIDDEN_TITLE])
        r = gw.osv_vulns(self.client(seen, {'vulns': self.fixtures()}), 'pypi:p@1.0', 10, B)
        self.assertEqual([x['id'] for x in r['vulns']], ['osv:GHSA-old1']); self.assertEqual(B.excluded, 6)
        self.assertEqual((r['package'], r['version'], r['ecosystem']), ('p', '1.0', 'PyPI')); self.assertNotIn('advisories_total_now', r)
        url, headers, body = seen[0]
        self.assertEqual((url, json.loads(body)), ('https://api.osv.dev/v1/query', {'package': {'name': 'p', 'ecosystem': 'PyPI'}, 'version': '1.0'}))
        self.assertEqual(headers['Content-Type'], 'application/json'); self.assertNotIn('Authorization', headers)   # OSV has no date filter: local barrier only
        self.assertNotIn(FAKE, url + body.decode() + json.dumps(headers)); self.assertNotIn('@', url)
        x = r['vulns'][0]; self.assertEqual((x['summary'], x['affected'][0]['events'][1], x['validity']), ('Sandbox escape', {'fixed': '2.0'}, 'advisory unchanged since before T'))

    def test_modified_after_T_is_masked_and_withdrawal_dated(self):
        x = gw.osv_item(self.vuln('GHSA-m', '2020-01-01T00:00:00Z', modified=F, withdrawn=F), barrier(), with_details=True)
        self.assertEqual((x['summary'], x['affected'], x['severity'], x['references'], x['date_modified'], x['withdrawn']), (None, None, None, None, None, None))
        self.assertIn('masked', x['abstract']); self.assertEqual(x['aliases'], ['CVE-0000-m'])
        y = gw.osv_item(self.vuln('GHSA-w', '2020-01-01T00:00:00Z', withdrawn='2021-01-01T00:00:00Z'), barrier(), with_details=True)
        self.assertEqual((y['withdrawn'], y['abstract']), ('2021-01-01T00:00:00Z', 'DETAILS'))

    def test_gateway_serves_vulns_and_read_osv_only_when_declared(self):
        seen = []
        g = gw.Gateway([self.plugin('code, osv')], T=T, run='o', state=self.d / 'state')
        self.assertIn('vulns', g.sources()['commands']); self.assertEqual(g.sources()['code_engines'], ['code', 'osv'])
        g.client = self.client(seen, {'vulns': self.fixtures()})
        r = g.call('vulns', 'pypi:p@1.0')
        self.assertEqual(([x['id'] for x in r['results']['vulns']], r['engine'], r['call']), (['osv:GHSA-old1', 'osv:GHSA-forb5', 'osv:GHSA-tit6'], 'osv', 1))   # no forbidden list here
        for bad in ('pypi:p', 'foo:p@1', 'pypi:p@1/2'): self.assertIn('expected form', g.call('vulns', bad)['refusal'], bad)
        g.client = self.client(seen, self.vuln('GHSA-old1', V + 'T00:00:00Z'))
        self.assertEqual(g.call('read', 'osv:GHSA-old1')['results']['abstract'], 'DETAILS'); self.assertEqual(seen[-1][0], 'https://api.osv.dev/v1/vulns/GHSA-old1')
        g.client = self.client(seen, self.vuln('GHSA-aft2', F + 'T00:00:00Z'))
        self.assertIn('refusal', g.call('read', 'osv:GHSA-aft2')['results'])
        g2 = gw.Gateway([self.plugin('openalex', 'other')], T=T, run='o2', state=self.d / 'state')
        for cmd, arg in (('vulns', 'pypi:p@1.0'), ('read', 'osv:GHSA-old1')):
            self.assertTrue(g2.call(cmd, arg)['refusal'].startswith("engine 'osv' not declared"), cmd)
        self.assertIn('refusal', gw.read('osv:GHSA-old1', barrier()))
        self.assertIn('api.osv.dev', sc.HOSTS); self.assertIn('osv', ck.WIRED)


class Fake302(urllib.request.BaseHandler):
    handler_order = 1

    def __init__(self): self.calls = []

    def https_open(self, req):
        self.calls.append((req.full_url, req.get_header('Authorization')))
        r = urllib.response.addinfourl(io.BytesIO(b''), email.message_from_string('Location: https://archive.softwareheritage.org/elsewhere\n'), req.full_url, 302)
        r.msg = 'Found'; return r


class SwhToken(Base):
    VISIT = {'snapshot': 'b' * 40, 'date': '2020-01-01T00:00:00Z', 'status': 'full'}

    def client(self, seen, status=200):
        c = sc.CodeClient(cache_dir=self.d / 'state'); c.sleep = lambda s: None; c.clock = lambda: 0.0
        def send(url, headers, body=None):
            seen.append((url, dict(headers)))
            if status != 200 and 'Authorization' in headers:
                raise urllib.error.HTTPError(url, status, 'Forbidden', {}, io.BytesIO(b'{"exception":"AuthenticationFailed","reason":"invalid_grant"}'))
            return 200, json.dumps([dict(self.VISIT, visit=1)] if '/visits/' in url else self.VISIT).encode()
        c._send = send; return c

    def test_token_sent_only_to_swh_with_its_interval(self):
        cfg = json.loads((P.parent / 'tools' / 'config.json').read_text())['code_intervals']
        seen = []; c = self.client(seen)
        sc.Provenance(c).visit('https://github.com/o/r')
        self.assertNotIn('Authorization', seen[-1][1])                                   # no token: anonymous
        os.environ['SWH_TOKEN'] = FAKE
        sc.Provenance(c).visit('https://github.com/o/r2')
        self.assertEqual(seen[-1][1]['Authorization'], 'Bearer ' + FAKE); self.assertNotIn(FAKE, seen[-1][0])
        self.assertEqual(c.waited[-1], ('archive.softwareheritage.org', cfg['archive.softwareheritage.org+token']))
        self.assertLess(cfg['archive.softwareheritage.org+token'], cfg['archive.softwareheritage.org'])
        del os.environ['SWH_TOKEN']; sc.Provenance(c).visit('https://github.com/o/r3')
        self.assertEqual(c.waited[-1], ('archive.softwareheritage.org', cfg['archive.softwareheritage.org']))
        for url, cred in (('https://api.github.com/x', 'SWH_TOKEN'), ('https://archive.softwareheritage.org/api/1/x/', 'VP_GITHUB_TOKEN'), ('https://pypi.org/pypi/p/1/json', 'SWH_TOKEN')):
            with self.assertRaises(ValueError) as cm: c.get(url, FAKE, cred=cred)
            self.assertEqual(str(cm.exception), 'credential_host', url)
        self.assertNotIn(FAKE, (self.d / 'state' / 'requests.jsonl').read_text())
        self.assertTrue(ck.CATALOGUE['SWH_TOKEN']['passed'])

    def test_no_second_request_on_redirect(self):
        os.environ['SWH_TOKEN'] = FAKE
        c = sc.CodeClient(cache_dir=self.d / 'state'); c.sleep = lambda s: None
        fake = Fake302(); c.opener.add_handler(fake)
        with self.assertRaises(ValueError) as cm: sc.Provenance(c).visit('https://github.com/o/r')
        self.assertEqual(str(cm.exception), 'redirect_refused'); self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0][1], 'Bearer ' + FAKE)

    def test_rejected_or_malformed_token_falls_back_and_is_flagged(self):
        for status in (401, 403):
            os.environ['SWH_TOKEN'] = FAKE; seen = []
            st = self.d / f'state{status}'
            g = gw.Gateway([self.plugin('provenance')], T='2026-01-02', run='s', state=st)
            g.client = self.client(seen, status); g.client.cache_dir = st
            r = g.call('provenance', 'https://github.com/o/r')
            self.assertEqual((r['results']['date_visited'], r['key_invalid']), ('2020-01-01T00:00:00Z', ['SWH_TOKEN']))
            self.assertEqual(['Authorization' in h for _, h in seen], [True, False])
            g.call('provenance', 'https://github.com/o/r2')                             # rest of the run: key-less, no new attempt
            self.assertEqual(['Authorization' in h for _, h in seen], [True, False, False])
            self.assertEqual(g.sources()['key_invalid'], ['SWH_TOKEN'])
            text = json.dumps(r) + (st / 'journal.jsonl').read_text() + (st / 'requests.jsonl').read_text() + (st / 'keys-invalid.json').read_text()
            self.assertNotIn(FAKE, text); self.assertIn('"key_invalid": ["SWH_TOKEN"]', (st / 'journal.jsonl').read_text())
        os.environ['SWH_TOKEN'] = 'BAD\nTOKEN'; seen = []; st = self.d / 'state-bad'
        c = self.client(seen); c.cache_dir = st
        sc.Provenance(c).visit('https://github.com/o/r')
        self.assertNotIn('Authorization', seen[-1][1]); self.assertEqual(sc.invalid_keys(st), {'SWH_TOKEN'})


class SwhVisitBeforeT(Base):
    """provenance <origin> reads the last visit WITH a snapshot dated before T (visit list, bisection on the visit number, at most
    software_heritage.visit_requests requests), never the latest visit; none -> refusal 'unavailable before T' (v0.6.1)."""
    def history(self, n, no_snapshot=()):
        """Visits 1..n, one per 3 days from 2020-01-01 (dates grow with the number); the numbers in no_snapshot failed (no snapshot)."""
        d0 = dt.date(2020, 1, 1)
        return {k: {'origin': 'https://github.com/o/r', 'visit': k, 'date': (d0 + dt.timedelta(days=3 * (k - 1))).isoformat() + 'T08:00:00+00:00',
                    'status': 'failed' if k in no_snapshot else 'full', 'snapshot': None if k in no_snapshot else f'{k:040x}'} for k in range(1, n + 1)}

    def client(self, hist, seen):
        self.k = getattr(self, 'k', 0) + 1                                  # a fresh cache per client: one history each
        c = sc.CodeClient(cache_dir=self.d / f'swh{self.k}'); c.sleep = lambda s: None; c.clock = lambda: 0.0
        def send(url, headers, body=None):
            seen.append(url); q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            self.assertIn('/visits/', url); self.assertNotIn('visit/latest', url)
            per = int(q['per_page'][0]); last = int(q['last_visit'][0]) if 'last_visit' in q else max(hist) + 1
            return 200, json.dumps([hist[k] for k in sorted(hist, reverse=True) if k < last][:per]).encode()
        c._send = send; return c

    def date_of(self, hist, k): return hist[k]['date']

    def test_last_visit_before_T_by_bisection(self):
        cfg = sc.CFG['software_heritage']; hist = self.history(1000)          # visit 1000 = 2028-03-..: the latest is far after T
        for target in (1, 2, 99, 500, 901, 999, 1000):
            seen = []; T_ = dt.date.fromisoformat(self.date_of(hist, target)[:10]) + dt.timedelta(days=1)   # T = the day after visit `target`
            v = sc.Provenance(self.client(hist, seen)).visit('https://github.com/o/r', T_)
            self.assertEqual((v['visit'], v['swhid'], v['date_visited']), (target, 'swh:1:snp:' + f'{target:040x}', self.date_of(hist, target)), target)
            self.assertLess(v['date_visited'][:10], T_.isoformat()); self.assertNotIn('found within', v['selected'])
            self.assertLessEqual(len(seen), cfg['visit_requests'], target)
            self.assertTrue(all(f'per_page={cfg["visits_per_page"]}' in u for u in seen))

    def test_visits_without_snapshot_are_skipped(self):
        hist = self.history(300, no_snapshot=(248, 249, 250)); seen = []
        T_ = dt.date.fromisoformat(self.date_of(hist, 250)[:10]) + dt.timedelta(days=1)
        v = sc.Provenance(self.client(hist, seen)).visit('https://github.com/o/r', T_)
        self.assertEqual(v['visit'], 247)

    def test_nothing_before_T_is_unavailable_never_the_latest(self):
        hist = self.history(250); seen = []
        r = sc.Provenance(self.client(hist, seen)).visit('https://github.com/o/r', dt.date(2019, 6, 1))
        self.assertEqual(set(r), {'refusal'}); self.assertTrue(r['refusal'].startswith('unavailable before T'))
        self.assertIn('2019-06-01', r['refusal'])
        seen = []; r = sc.Provenance(self.client(self.history(3, no_snapshot=(1, 2, 3)), seen)).visit('https://github.com/o/r', dt.date(2030, 1, 1))
        self.assertTrue(r['refusal'].startswith('unavailable before T')); self.assertEqual(len(seen), 1)   # short list read once
        g = gw.Gateway([self.plugin('provenance')], T='2019-06-01', run='u', state=self.d / 'state')
        g.client = self.client(hist, [])
        out = g.call('provenance', 'https://github.com/o/r')
        self.assertTrue(out['results']['refusal'].startswith('unavailable before T')); self.assertNotIn('warning', out)
        g = gw.Gateway([self.plugin('provenance')], T='2020-03-01', run='u2', state=self.d / 'state')
        g.client = self.client(hist, [])
        out = g.call('provenance', 'https://github.com/o/r')                  # through the gateway: the visit before T, the barrier keeps it
        self.assertEqual((out['results']['visit'], out['excluded_post_T_or_forbidden']), (20, 0)); self.assertLess(out['results']['date_visited'], '2020-03-01')

    def test_bound_on_requests(self):
        saved = dict(sc.CFG['software_heritage'])
        try:
            sc.CFG['software_heritage']['visit_requests'] = 2; hist = self.history(1000); seen = []
            T_ = dt.date.fromisoformat(self.date_of(hist, 10)[:10]) + dt.timedelta(days=1)
            r = sc.Provenance(self.client(hist, seen)).visit('https://github.com/o/r', T_)
            self.assertEqual(len(seen), 2)
            self.assertTrue(r['refusal'].startswith('unavailable before T') and 'within 2 visit-list requests' in r['refusal'], r)
            seen = []; T_ = dt.date.fromisoformat(self.date_of(hist, 700)[:10]) + dt.timedelta(days=1)
            v = sc.Provenance(self.client(hist, seen)).visit('https://github.com/o/r', T_)
            self.assertLess(v['visit'], 700); self.assertIn('found within 2 requests', v['selected'])   # an earlier visit, flagged as such
            self.assertLess(v['date_visited'][:10], T_.isoformat())
        finally: sc.CFG['software_heritage'].update(saved)


class Resp(io.BytesIO):
    def __enter__(self): return self

    def __exit__(self, *a): self.close()


class InvalidKey(Base):
    def opener(self, answers):
        """urlopen replaced: answers(url) -> bytes or raises; every URL recorded."""
        def urlopen(req, timeout=None):
            self.urls.append(req.full_url); return Resp(answers(req.full_url))
        return urlopen

    def ncbi(self, url):
        if 'api_key=' in url:
            raise urllib.error.HTTPError(url, 400, 'Bad Request', {}, io.BytesIO(('{"error":"API key invalid","api-key":"' + FAKE + '","type":"invalid"}').encode()))
        if 'esearch' in url: return b'{"esearchresult":{"idlist":["1"],"count":"1"}}'
        return json.dumps({'result': {'1': {'title': 'Old', 'history': [{'pubstatus': 'entrez', 'date': '2020/01/01 00:00'}], 'epubdate': '2020 Jan 1',
                                            'pubdate': '2020', 'authors': [{'name': 'A'}], 'articleids': []}}}).encode()

    def test_ncbi_invalid_key_is_dropped_for_the_run(self):
        os.environ['NCBI_API_KEY'] = FAKE; urllib.request.urlopen = self.opener(self.ncbi)
        g = gw.Gateway([self.plugin('pubmed')], T=T, run='k', state=self.d / 'state')
        self.assertEqual(gw.interval('eutils.ncbi.nlm.nih.gov'), 0.11)
        r = g.search('pubmed', 'semaglutide')
        self.assertEqual(([x['id'] for x in r['results']], r['key_invalid']), (['pmid:1'], ['NCBI_API_KEY']))
        self.assertEqual(['api_key=' in u for u in self.urls], [True, False, False])     # esearch with key (400), esearch without, esummary without
        self.assertEqual(gw.interval('eutils.ncbi.nlm.nih.gov'), 0.45); self.assertEqual(gw.ncbi_key(), '')
        r2 = g.search('pubmed', 'other words')
        self.assertFalse(any('api_key=' in u for u in self.urls[3:])); self.assertEqual(r2['key_invalid'], ['NCBI_API_KEY'])
        s = g.sources(); self.assertEqual((s['key_invalid'], s['keys_present']), (['NCBI_API_KEY'], []))
        text = json.dumps([r, r2, s]) + (self.d / 'state' / 'journal.jsonl').read_text() + (self.d / 'state' / 'keys-invalid.json').read_text()
        self.assertNotIn(FAKE, text)
        self.assertFalse(any(FAKE.encode() in f.read_bytes() for f in (self.d / 'state' / 'cache').iterdir()), 'the 400 body (it echoes the key) is never cached')

    def test_other_400_is_not_a_key_rejection(self):
        os.environ['NCBI_API_KEY'] = FAKE; gw.time.sleep = lambda s: None
        def bad(url): raise urllib.error.HTTPError(url, 400, 'Bad Request', {}, io.BytesIO(b'{"error":"Invalid query"}'))
        urllib.request.urlopen = self.opener(bad)
        g = gw.Gateway([self.plugin('pubmed')], T=T, run='k2', state=self.d / 'state')
        r = g.search('pubmed', 'x')
        self.assertIn('error', r['results']); self.assertNotIn('key_invalid', r); self.assertEqual(sc.invalid_keys(self.d / 'state'), set())
        self.assertTrue(all('api_key=' in u for u in self.urls))

    def test_openalex_rejected_key_401_403(self):
        for code in (401, 403):
            os.environ['OPENALEX_KEY'] = FAKE; self.urls = []; st = self.d / f'oa{code}'
            def oa(url, code=code):
                if 'api_key=' in url: raise urllib.error.HTTPError(url, code, 'Unauthorized', {}, io.BytesIO(b'{"error":"Invalid API key"}'))
                if 'openalex' in url: return json.dumps({'results': [{'id': 'https://openalex.org/W1', 'doi': 'https://doi.org/10.1/old', 'title': 'Old', 'publication_date': '2020-01-01'}], 'meta': {'count': 1}}).encode()
                return crossref_answer(url, {'10.1/old': ('2020-01-01', '2020-01-02')})
            urllib.request.urlopen = self.opener(oa)
            g = gw.Gateway([self.plugin('openalex')], T=T, run='oa', state=st)
            r = g.search('openalex', 'x')
            self.assertEqual(([x['id'] for x in r['results']], r['key_invalid']), (['doi:10.1/old'], ['OPENALEX_KEY']))
            self.assertEqual([('api_key=' in u) for u in self.urls if 'openalex' in u], [True, False])
            self.assertEqual(gw.oa_key(), ''); self.assertNotIn(FAKE, json.dumps(r))
        self.assertEqual(gw.strip_key('https://h/x?a=1&api_key=K&b=2'), 'https://h/x?a=1&b=2')
        self.assertEqual(gw.strip_key('https://h/works/doi:10.1/x?api_key=K'), 'https://h/works/doi:10.1/x')
        self.assertEqual(gw.strip_key('https://h/x?api_key=K&b=2'), 'https://h/x?b=2')


if __name__ == '__main__':
    unittest.main()
