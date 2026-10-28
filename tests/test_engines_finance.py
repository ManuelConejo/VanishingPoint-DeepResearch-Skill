#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline tests of the finance data engines (v0.4.9, plugins/finance.md sections 7-8): dbnomics (keyless, current values) and fred (FRED/ALFRED,
FRED_API_KEY). Observations whose period ends on/after T are dropped (partial year, quarter, month, week, day), unknown period forms dropped;
every DBnomics value is marked as_of "now"; FRED is read at the ALFRED vintage of the eve of T (realtime_start = realtime_end = eve in the URL);
no key -> skipped with 0 request; FRED 400 about api_key -> key_invalid, 0 request afterwards; the key never appears in output, journal or cache;
new identifier prefixes dbnomics: and fred: accepted by validate_result, verifier and export_data (type dataset).
Transport replaced (urllib.request.urlopen under gateway.fetch): no network. Run: python3 -I tests/test_engines_finance.py"""
import io, json, os, pathlib, sys, tempfile, unittest, urllib.error, urllib.parse
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import gateway as gw, code_sources as sc, check_keys as ck, setup_keys as SK, validate_result as VR, verifier as VF, export_data as ED   # noqa: E702

T, EVE = '2024-06-15', '2024-06-14'
FAKE = 'f00dfeedf00dfeedf00dfeedf00dfeed'
FIN = P.parent / 'plugins' / 'finance.md'
NOW = gw.AS_OF_NOW


class Resp(io.BytesIO):
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


def dbn_series(periods, values):
    return {'provider': {'code': 'ECB', 'terms_of_use': 'https://example.org/terms'},
            'series': {'docs': [{'provider_code': 'ECB', 'dataset_code': 'ICP', 'dataset_name': 'Indices', 'series_code': 'M.U2.X', 'series_name': 'HICP euro area',
                                 '@frequency': 'mixed', 'indexed_at': '2026-10-27T06:28:22Z', 'period': periods, 'value': values}]}}


class Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.saved = (gw.STATE, gw.urllib.request.urlopen, dict(gw.INTERVAL))
        gw.INTERVAL.update({'api.db.nomics.world': 0, 'api.stlouisfed.org': 0})   # no pacing offline
        gw.STATE = pathlib.Path(self.tmp.name) / 'state'                                # direct engine calls: cache in the temporary dir
        self.env = {k: os.environ.pop(k) for k in ('FRED_API_KEY', 'HOME', 'VP_CONTACT') if k in os.environ}; os.environ['HOME'] = self.tmp.name
        self.calls, self.route = [], None
        def urlopen(req, timeout=None):
            url = req.full_url; self.calls.append(url); st, body = self.route(url)
            if st != 200: raise urllib.error.HTTPError(url, st, 'stub', {}, io.BytesIO(json.dumps(body).encode()))
            return Resp(json.dumps(body).encode())
        gw.urllib.request.urlopen = urlopen

    def tearDown(self):
        gw.STATE, gw.urllib.request.urlopen, iv = self.saved; gw.INTERVAL.clear(); gw.INTERVAL.update(iv)
        for k in ('FRED_API_KEY', 'HOME', 'VP_CONTACT'): os.environ.pop(k, None)
        os.environ.update(self.env); self.tmp.cleanup()

    def gate(self, run='r'):
        return gw.Gateway([str(FIN)], T=T, run=run, state=pathlib.Path(self.tmp.name) / 'state')

    def no_key_anywhere(self):
        st = pathlib.Path(self.tmp.name) / 'state'
        for f in st.rglob('*'):
            if f.is_file(): self.assertNotIn(FAKE.encode(), f.read_bytes(), f.name)

    def test_period_end(self):
        pe = lambda p, f=None: str(gw.period_end(p, f))
        self.assertEqual([pe(x) for x in ('2024', '2024-Q2', '2024-S1', '2024-H2', '2024-B3', '2024-06', '2024-W24', '2024-06-14', '2024-13', '2024-Q5', 'x')],
                         ['2024-12-31', '2024-06-30', '2024-06-30', '2024-12-31', '2024-06-30', '2024-06-30', '2024-06-16', '2024-06-14', 'None', 'None', 'None'])
        self.assertEqual([pe('2024-04-01', f) for f in ('A', 'Q', 'M', 'SA', 'W', 'BW', 'D', '?')],
                         ['2025-03-31', '2024-06-30', '2024-04-30', '2024-09-30', '2024-04-07', '2024-04-14', '2024-04-01', 'None'])

    def test_dbnomics_read_barrier_and_as_of(self):
        per = ['2023', '2024', '2024-Q1', '2024-Q2', '2024-05', '2024-06', '2024-W23', '2024-W24', '2024-06-14', '2024-06-15', 'odd']
        self.route = lambda url: (200, dbn_series(per, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 'NA', 11.0]))
        out = self.gate().read('dbnomics:ECB/ICP/M.U2.X')
        r = out['results']
        self.assertEqual([o['period'] for o in r['observations']], ['2023', '2024-Q1', '2024-05', '2024-W23', '2024-06-14'])
        self.assertTrue(all(o['period_end'] < T for o in r['observations']))
        self.assertTrue(all(o['as_of'] == NOW for o in r['observations'])); self.assertEqual((r['as_of'], r['vintage']), (NOW, None))
        self.assertIn('released on/after T', r['caveat']); self.assertEqual(r['dropped_at_or_after_T'], 6); self.assertEqual(out['excluded_post_T_or_forbidden'], 6)
        self.assertEqual(r['date'], '2024-06-14'); self.assertNotIn('date_indexed', r); self.assertEqual(r['type'], 'dataset')
        self.assertTrue(self.calls[0].startswith('https://api.db.nomics.world/v22/series/ECB/ICP/M.U2.X?observations=1'))

    def test_dbnomics_read_nothing_before_T_and_form(self):
        self.route = lambda url: (200, dbn_series(['2024-06', '2024-Q3', '2025'], [1, 2, 3]))
        g = self.gate()
        self.assertIn('no observation', g.read('dbnomics:ECB/ICP/M.U2.X')['results']['refusal'])
        n = len(self.calls); self.assertIn('expected form', g.read('dbnomics:ECB')['results']['refusal']); self.assertEqual(len(self.calls), n)
        self.assertEqual(g.citing('dbnomics:ECB/ICP/M.U2.X')['results'], []); self.assertEqual(g.citing('fred:UNRATE')['index_total'], gw.DATA_NO_CHAIN)

    def test_dbnomics_search(self):
        def route(url):
            if '/v22/search?' in url: return 200, {'results': {'num_found': 2, 'docs': [{'provider_code': 'ECB', 'code': 'ICP', 'nb_matching_series': 2}, {'provider_code': 'X', 'code': 'Y', 'nb_matching_series': 0}]}}
            return 200, {'series': {'docs': [{'provider_code': 'ECB', 'dataset_code': 'ICP', 'series_code': 'A', 'series_name': 'HICP euro area'},
                                             {'provider_code': 'ECB', 'dataset_code': 'ICP', 'series_code': 'B', 'series_name': 'A forbidden systematic review of everything that matters here'}]}}
        self.route = route
        B = gw.Barrier(T, [], ['A forbidden systematic review of everything that matters here'])
        items, total = gw.search_dbnomics('hicp euro area', 10, B)
        self.assertEqual(([x['id'] for x in items], total, B.excluded), (['dbnomics:ECB/ICP/A'], 2, 1))
        self.assertIn(NOW, items[0]['dating']); self.assertEqual(len(self.calls), 2)   # the dataset with 0 matching series is not opened
        self.assertIn('q=hicp+euro+area', self.calls[1]); self.assertIn('observations=0', self.calls[1])

    def test_fred_without_key_zero_request(self):
        self.route = lambda url: self.fail('no request without a key')
        g = self.gate()
        for out in (g.search('fred', 'unemployment'), g.read('fred:UNRATE')):
            self.assertEqual((out['results']['status'], out['results']['reason']), ('skipped', 'credential_missing'))
        self.assertEqual(self.calls, []); self.assertIn('dbnomics', g.search('fred', 'x')['results']['refusal'])

    def test_fred_vintage_eve_of_T(self):
        os.environ['FRED_API_KEY'] = FAKE
        def route(url):
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            self.assertEqual((q['realtime_start'], q['realtime_end'], q['api_key']), ([EVE], [EVE], [FAKE]))
            if '/series/observations' in url:
                self.assertEqual(q['observation_end'], [EVE])
                return 200, {'observations': [{'date': '2023-10-01', 'value': '1.5', 'realtime_start': '2024-03-28'}, {'date': '2024-01-01', 'value': '.', 'realtime_start': '2024-05-30'},
                                              {'date': '2024-04-01', 'value': '2.9', 'realtime_start': '2024-06-14'}, {'date': '2023-07-01', 'value': '9', 'realtime_start': '2024-07-01'}]}
            if '/series/search' in url:
                self.assertEqual(q['search_text'], ['gdp'])
                return 200, {'count': 3, 'seriess': [{'id': 'GDPC1', 'title': 'Real GDP', 'frequency_short': 'Q', 'observation_start': '1947-01-01'},
                                                      {'id': 'NEW', 'title': 'New', 'frequency_short': 'M', 'observation_start': '2024-07-01'}]}
            return 200, {'seriess': [{'id': 'GDPC1', 'title': 'Real GDP', 'frequency_short': 'Q', 'observation_start': '1947-01-01'}]}
        self.route = route; g = self.gate()
        s = g.search('fred', 'gdp')
        self.assertEqual(([x['id'] for x in s['results']], s['index_total']), (['fred:GDPC1'], 3))
        r = g.read('fred:GDPC1')['results']
        self.assertEqual([(o['period'], o['value'], o['vintage']) for o in r['observations']], [('2023-10-01', '1.5', '2024-03-28'), ('2024-01-01', None, '2024-05-30')])
        self.assertEqual((r['vintage'], r['date'], r['dropped_at_or_after_T']), (EVE, '2024-03-31', 1)); self.assertIn('as known on the eve of T', r['as_of'])
        self.assertTrue(all(c.startswith('https://api.stlouisfed.org/fred/') for c in self.calls))
        self.assertNotIn(FAKE, json.dumps([s, r])); self.no_key_anywhere()

    def test_fred_invalid_key(self):
        os.environ['FRED_API_KEY'] = FAKE
        self.route = lambda url: (400, {'error_code': 400, 'error_message': 'Bad Request.  The value for variable api_key is not registered.'})
        g = self.gate()
        out = g.search('fred', 'unemployment')
        self.assertEqual((out['results']['status'], out['results']['reason'], out['key_invalid']), ('skipped', 'key_invalid', ['FRED_API_KEY']))
        self.assertEqual(len(self.calls), 1)                                        # 400 never retried
        out = g.read('fred:UNRATE'); self.assertEqual((out['results']['reason'], len(self.calls)), ('key_invalid', 1))   # no request afterwards
        self.assertNotIn(FAKE, json.dumps(out)); self.no_key_anywhere()
        self.assertNotIn(FAKE, (pathlib.Path(self.tmp.name) / 'state' / 'journal.jsonl').read_text())

    def test_fred_other_400_is_a_refusal(self):
        os.environ['FRED_API_KEY'] = FAKE
        self.route = lambda url: (400, {'error_code': 400, 'error_message': 'Bad Request.  The series does not exist in ALFRED but may exist in FRED.'})
        out = self.gate().read('fred:SP500')
        self.assertIn('not served at the vintage of the eve of T', out['results']['refusal']); self.assertNotIn('key_invalid', out)

    def test_prefixes_and_catalogue(self):
        for i in ('dbnomics:ECB/ICP/M.U2.N.000000.4.ANR', 'dbnomics:INSEE/CHOMAGE-TRIM-NATIONAL/T.CTTXC.TAUX.FR-D976.0.00-.POURCENT.CVS.FALSE', 'fred:UNRATE'):
            self.assertTrue(VR.ID.match(i), i)
        self.assertEqual(VF.ident_of({'fred': 'UNRATE'}), 'fred:UNRATE'); self.assertEqual(VF.ident_of({'dbnomics': 'ECB/ICP/A'}), 'dbnomics:ECB/ICP/A')
        self.assertEqual((ED.kind(['fred:UNRATE'], None, None, None), ED.kind(['dbnomics:ECB/ICP/A'], None, None, None)), ('dataset', 'dataset'))
        c = ck.CATALOGUE['FRED_API_KEY']; self.assertEqual((c['engine'], c['passed']), ('fred', True)); self.assertIn('fred', ck.WIRED)
        self.assertTrue(next(e for e in SK.entries() if e['name'] == 'fred')['wired'])
        g = self.gate(); self.assertIn('dbnomics', g.engines); self.assertIn('fred', g.engines); self.assertNotIn('fred', g.not_wired)


if __name__ == '__main__':
    unittest.main()
