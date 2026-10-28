#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of the PISTE engines of the gateway (plugins/law.md sections 5-6): judilibre and legifrance, with a stubbed HTTPS handler
plugged into the real opener (no network). Token request shape, cache and expiry; no secret in URLs, receipts, journal, cache or output;
bearer never sent on a redirect nor to another host; skipped with 0 request without the pair; key_invalid on 401; date barrier per engine;
Legifrance version in force on the eve of T with an exclusive end; operative part kept; law_checks on a Legifrance record."""
import email.message, io, json, os, pathlib, sys, tempfile, time, unittest, urllib.parse, urllib.request, urllib.response
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import gateway as gw, code_sources as sc, law_checks as L   # noqa: E702

CID, CSEC, TOK = 'CID-SECRET-1234abcd', 'CSEC-SECRET-5678efgh', 'TOK-SECRET-abcdef0123'
SECRETS = (CID, CSEC, TOK)
LAW = P.parent / 'plugins' / 'law.md'


def ms(day, paris=True):
    """Epoch milliseconds of `day` at Paris midnight as Legifrance serves it (22:00 UTC the day before in summer), else 00:00 UTC."""
    import datetime as dt
    d = dt.date.fromisoformat(day) - dt.timedelta(days=1 if paris else 0)
    return int(dt.datetime(d.year, d.month, d.day, 22 if paris else 0, tzinfo=dt.timezone.utc).timestamp() * 1000)


class Stub(urllib.request.BaseHandler):
    """Answers every https request from `route(method, url, headers, body) -> (status, json-or-bytes, extra headers)`; records each call."""
    handler_order = 100

    def __init__(self, route): self.route, self.calls = route, []

    def https_open(self, req):
        h = {k.lower(): v for k, v in req.header_items()}
        body = req.data.decode() if req.data else None
        self.calls.append({'method': req.get_method(), 'url': req.full_url, 'headers': h, 'body': body})
        st, data, extra = (self.route(req.get_method(), req.full_url, h, body) + ({},))[:3]
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        m = email.message.Message()
        for k, v in dict({'Content-Type': 'application/json'}, **extra).items(): m[k] = v
        r = urllib.response.addinfourl(io.BytesIO(raw), m, req.full_url, st); r.msg = 'stub'
        return r


def token_ok(method, url, h, body):
    if url == gw.PISTE_OAUTH: return 200, {'access_token': TOK, 'token_type': 'Bearer', 'expires_in': 3600, 'scope': 'openid'}
    return None


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.state = pathlib.Path(self.tmp.name) / 'state'
        gw.STATE = self.state; self.saved = {k: os.environ.pop(k, None) for k in gw.PISTE_KEYS}
        self.home = os.environ.get('HOME'); os.environ['HOME'] = self.tmp.name                  # no ~/.config/vp key file
        self.iv = dict(gw.INTERVAL); gw.INTERVAL.update({'oauth.piste.gouv.fr': 0, 'api.piste.gouv.fr': 0})
        self.orig = gw._PISTE_OPENER; gw._PISTE_OPENER = urllib.request.build_opener(sc._NoRedirect())

    def tearDown(self):
        gw._PISTE_OPENER = self.orig; gw.INTERVAL.clear(); gw.INTERVAL.update(self.iv)
        for k, v in self.saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        if self.home is None: os.environ.pop('HOME', None)
        else: os.environ['HOME'] = self.home
        self.tmp.cleanup()

    def keys(self): os.environ['PISTE_CLIENT_ID'] = CID; os.environ['PISTE_CLIENT_SECRET'] = CSEC

    def stub(self, api):
        """api(method, url, headers, body) -> (status, data[, headers]) for api.piste.gouv.fr; the OAuth host gives TOK."""
        s = Stub(lambda m, u, h, b: token_ok(m, u, h, b) or api(m, u, h, b)); gw._PISTE_OPENER.add_handler(s); return s

    def gateway(self, T): return gw.Gateway([LAW], T=T, run='t-piste', state=self.state)

    def no_leak(self, *outputs):
        files = [f for f in self.state.rglob('*') if f.is_file() and f.name != gw.PISTE_TOKEN]
        for f in files:
            t = f.read_bytes().decode('utf-8', 'replace')
            for s in SECRETS: self.assertNotIn(s, t, f.name)
        for o in outputs:
            for s in SECRETS: self.assertNotIn(s, json.dumps(o, ensure_ascii=False))
        tf = self.state / gw.PISTE_TOKEN
        if tf.exists():
            self.assertEqual(tf.stat().st_mode & 0o777, 0o600); t = tf.read_text()
            self.assertNotIn(CID, t); self.assertNotIn(CSEC, t)


def jl(did, date, **k): return dict({'id': did, 'jurisdiction': 'cc', 'chamber': 'soc', 'number': '21-' + did[-5:], 'ecli': 'ECLI:FR:CCASS:' + did,
                                     'decision_date': date, 'solution': 'rejet', 'publication': ['b'], 'type': 'arret', 'summary': 'S'}, **k)


class Credentials(Base):
    def test_skipped_without_keys_zero_request(self):
        s = self.stub(lambda *a: (500, {}))
        g = self.gateway('2020-06-01')
        src = g.sources(); self.assertIn('judilibre', src['engines']); self.assertIn('legifrance', src['engines'])
        self.assertIn('search-judilibre', src['commands']); self.assertNotIn('judilibre', src['not_wired'])
        for cmd, arg in (('search-judilibre', 'bail commercial'), ('search-legifrance', 'responsabilite'), ('read', 'legi:LEGIARTI000006438819'),
                         ('read', 'judilibre:5fca56cd0a790c1ec36ddc07'), ('read', 'jorf:JORFTEXT000032004939')):
            r = g.call(cmd, arg)['results']
            self.assertEqual((r['status'], r['reason'], r['requests']), ('skipped', 'not_configured', 0), cmd)
            self.assertIn('refusal', r)
        os.environ['PISTE_CLIENT_ID'] = CID                                                      # half the pair: still skipped
        self.assertEqual(g.call('search-judilibre', 'bail')['results']['reason'], 'not_configured')
        self.assertEqual(s.calls, []); self.assertFalse((self.state / 'requests.jsonl').exists())

    def test_token_shape_cache_and_expiry(self):
        self.keys(); s = self.stub(lambda m, u, h, b: (200, {'results': [], 'total': 0}))
        B = gw.Barrier('2020-06-01')
        gw.search_judilibre('bail', 5, B); gw.search_judilibre('licenciement', 5, B)
        tok = [c for c in s.calls if c['url'] == gw.PISTE_OAUTH]; api = [c for c in s.calls if c['url'] != gw.PISTE_OAUTH]
        self.assertEqual((len(tok), len(api)), (1, 2))                                          # token cached for the second call
        t = tok[0]; f = urllib.parse.parse_qs(t['body'])
        self.assertEqual(t['method'], 'POST'); self.assertEqual(t['headers']['content-type'], 'application/x-www-form-urlencoded')
        self.assertEqual({k: v[0] for k, v in f.items()}, {'grant_type': 'client_credentials', 'client_id': CID, 'client_secret': CSEC, 'scope': 'openid'})
        self.assertNotIn('authorization', t['headers']); self.assertNotIn(CSEC, t['url'])
        for c in api:
            self.assertEqual(c['headers']['authorization'], 'Bearer ' + TOK); self.assertTrue(c['url'].startswith('https://api.piste.gouv.fr/cassation/judilibre/v1.0/search?'))
            for x in SECRETS: self.assertNotIn(x, c['url'])
        c = json.loads((self.state / gw.PISTE_TOKEN).read_text()); c['expires_at'] = time.time() + 30           # less than 60 s left: refreshed
        (self.state / gw.PISTE_TOKEN).write_text(json.dumps(c))
        gw.search_judilibre('preavis', 5, B)
        self.assertEqual(len([c for c in s.calls if c['url'] == gw.PISTE_OAUTH]), 2)
        os.environ['PISTE_CLIENT_SECRET'] = CSEC + 'x'                                           # other credentials: the cached token is not reused
        gw.search_judilibre('rupture', 5, B)
        self.assertEqual(len([c for c in s.calls if c['url'] == gw.PISTE_OAUTH]), 3)
        self.no_leak()

    def test_no_secret_anywhere_through_the_gateway(self):
        self.keys()
        def api(m, u, h, b):
            if 'judilibre' in u and '/search' in u: return 200, {'results': [jl('5fca56cd0a790c1ec36dd001', '2019-03-06')], 'total': 1}
            if 'judilibre' in u: return 200, dict(jl('5fca56cd0a790c1ec36dd001', '2019-03-06'), text='Attendu que... PAR CES MOTIFS, la Cour : REJETTE le pourvoi')
            return 200, {'results': [], 'totalResultNumber': 0}
        s = self.stub(api); g = self.gateway('2020-06-01')
        outs = [g.call('search-judilibre', 'bail commercial', court='cc', chamber='civ3'), g.call('read', 'judilibre:5fca56cd0a790c1ec36dd001'),
                g.call('search-legifrance', 'article 1382 code civil'), g.sources()]
        self.assertEqual(outs[0]['results'][0]['id'], 'judilibre:5fca56cd0a790c1ec36dd001'); self.assertEqual(outs[0]['filters'], {'court': 'cc', 'chamber': 'civ3'})
        self.assertIn('jurisdiction=cc', s.calls[1]['url']); self.assertIn('chamber=civ3', s.calls[1]['url'])
        rec = [json.loads(l) for l in (self.state / 'requests.jsonl').read_text().splitlines()]
        self.assertEqual({r['host'] for r in rec}, {'oauth.piste.gouv.fr', 'api.piste.gouv.fr'})
        for r in rec: self.assertFalse(set(r) & {'url', 'headers', 'body', 'token'}, r)
        self.no_leak(*outs)

    def test_redirect_refused_and_hosts(self):
        self.keys(); s = self.stub(lambda m, u, h, b: (302, b'', {'Location': 'https://evil.example/steal'}))
        r = self.gateway('2020-06-01').call('search-judilibre', 'bail')
        self.assertIn('redirect_refused', r['results']['error'])
        self.assertEqual([c['url'].split('/')[2] for c in s.calls], ['oauth.piste.gouv.fr', 'api.piste.gouv.fr'])   # no request to the redirect target
        for url, cred in (('http://api.piste.gouv.fr/x', 'bearer'), ('https://evil.example/x', None), ('https://api.piste.gouv.fr:8443/x', 'bearer'),
                          ('https://oauth.piste.gouv.fr/x', 'bearer'), ('https://api.piste.gouv.fr/x', 'credentials')):
            with self.assertRaises(ValueError, msg=url): gw.piste_http(url, None, {'Authorization': 'Bearer ' + TOK}, cred=cred)
        self.assertEqual(len(s.calls), 2)
        self.no_leak(r)

    def test_key_invalid_on_401(self):
        self.keys(); s = Stub(lambda m, u, h, b: (401, {'error': 'invalid_client'})); gw._PISTE_OPENER.add_handler(s)
        g = self.gateway('2020-06-01'); r = g.call('search-legifrance', 'bail')
        self.assertEqual((r['results']['status'], r['results']['reason']), ('skipped', 'key_invalid')); self.assertEqual(r['key_invalid'], list(gw.PISTE_KEYS))
        self.assertEqual(len(s.calls), 1)
        r2 = g.call('read', 'legi:LEGIARTI000006438819')
        self.assertEqual(r2['results']['reason'], 'key_invalid'); self.assertEqual(len(s.calls), 1)          # 0 request afterwards
        self.assertIn('PISTE_CLIENT_ID', g.sources()['key_invalid'])
        self.assertIn('PISTE_CLIENT_SECRET', json.loads((self.state / 'journal.jsonl').read_text().splitlines()[-1])['key_invalid'])
        self.no_leak(r, r2)

    def test_api_401_twice_then_403(self):
        self.keys(); s = self.stub(lambda m, u, h, b: (401, {}))
        r = gw.search_legifrance('bail', 5, gw.Barrier('2020-06-01'))
        self.assertEqual(r[0]['reason'], 'key_invalid')
        self.assertEqual([c['url'] == gw.PISTE_OAUTH for c in s.calls], [True, False, True, False])          # one fresh token, then key_invalid
        self.tearDown(); self.setUp(); self.keys(); self.stub(lambda m, u, h, b: (403, {}))
        r = gw.read_judilibre('5fca56cd0a790c1ec36dd001', gw.Barrier('2020-06-01'))
        self.assertEqual(r['reason'], 'not_subscribed'); self.assertFalse(sc.invalid_keys(self.state))


class Judilibre(Base):
    def test_barrier_search(self):
        self.keys(); T = '2023-06-01'
        rows = [jl('aaaaaaaaaa01', '2023-05-31'), jl('aaaaaaaaaa02', '2023-06-01'), jl('aaaaaaaaaa03', '2023-07-01'), jl('aaaaaaaaaa04', '2022'),
                jl('aaaaaaaaaa05', '2023'), jl('aaaaaaaaaa06', None), jl('aaaaaaaaaa07', '2020-01-10'), jl('aaaaaaaaaa08', '2020-01-10', ecli='ECLI:FR:CCASS:2020:SO00042'),
                jl('aaaaaaaaaa09', '2020-01-10', number='19-12.345', numbers=['19-12.345'], chamber='civ1'), jl('aaaaaaaaaa10', '2021-02-02', update_date='2024-01-01'),
                jl('aaaaaaaaaa11', '2021-02-02', update_date='2021-03-01')]
        s = self.stub(lambda m, u, h, b: (200, {'results': rows, 'total': len(rows)}))
        B = gw.Barrier(T, forbidden_dois=['judilibre:aaaaaaaaaa07', 'ECLI:FR:CCASS:2020:SO00042'],
                       forbidden_titles=['Cour de cassation, première chambre civile, 2020-01-10, n° 19-12.345'])
        out, tot = gw.search_judilibre('bail', 50, B)
        self.assertEqual([o['id'][-2:] for o in out], ['01', '04', '10', '11'])      # day T, after T, partial 2023, no date, forbidden id/ECLI/title refused
        self.assertEqual(B.excluded, 7)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(s.calls[-1]['url']).query))
        self.assertEqual((q['date_end'], q['date_start'], q['query'], q['operator']), ('2023-05-31', '1800-01-01', 'bail', 'and'))
        o = {x['id'][-2:]: x for x in out}
        self.assertEqual((o['01']['order'], o['01']['tier'], o['01']['court'], o['01']['ecli']), ('FR-JUD', 'primary', 'cc', 'ECLI:FR:CCASS:aaaaaaaaaa01'))
        self.assertIn('masked', o['10']['metadata']); self.assertNotIn('publication', o['10'])               # updated after T: editorial metadata masked
        self.assertEqual(o['11']['publication'], ['b']); self.assertIn('metadata_as_of', o['01'])
        self.assertIn('bounded', tot)
        self.assertEqual(gw.search_judilibre('x', 5, B, court='CE')[0], []); self.assertEqual(gw.search_judilibre('x', 5, B, date_from='2024-01-01')[0], [])

    def test_read_operative_part_and_history(self):
        self.keys(); head = 'Attendu que ' * 3000; tail = 'PAR CES MOTIFS, la Cour : CASSE ET ANNULE, en toutes ses dispositions, l arret rendu le 3 mai 2018.'
        text = head + 'PAR CES MOTIFS (cite plus haut) ' + 'motif ' * 500 + tail
        docs = {'d1': jl('dddddddddd01', '2019-05-02', jurisdiction='ca', text=text, update_date='2019-06-01',
                         forward={'id': 'dddddddddd02', 'date': '2020-03-04', 'solution': 'Cassation', 'title': 'Cass. soc.'}, contested={'date': '2017-01-01', 'title': 'TJ'},
                         timeline=[{'date': '2018-01-01', 'title': 'a'}, {'date': '2025-01-01', 'title': 'late'}]),
                'd3': jl('dddddddddd03', '2019-05-02', jurisdiction='ca', text=text, zones={'dispositif': [{'start': len(text) - len(tail), 'end': len(text)}]},
                         forward={'id': 'dddddddddd04', 'date': '2024-03-04', 'solution': 'Cassation'}),
                'd5': jl('dddddddddd05', '2019-05-02', jurisdiction='ca', text='court', forward={'date': '2020-01-01', 'solution': 'Rejet'}),
                'd6': jl('dddddddddd06', '2025-05-02', text='late')}
        def api(m, u, h, b):
            i = urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)['id'][0]
            return (200, docs['d' + str(int(i[-2:]))]) if 'd' + str(int(i[-2:])) in docs else (404, {})
        self.stub(api); B = gw.Barrier('2023-06-01')
        r = gw.read_judilibre('dddddddddd01', B)
        self.assertTrue(r['abstract'].endswith(tail)); self.assertIn('elided; operative part follows', r['abstract'])
        self.assertEqual(r['set_aside_by'], ['dddddddddd02']); self.assertEqual([x['title'] for x in r['timeline']], ['a'])
        r3 = gw.read_judilibre('dddddddddd03', B)
        self.assertTrue(r3['abstract'].endswith(tail)); self.assertNotIn('set_aside_by', r3); self.assertIn('masked', r3['history'])
        self.assertEqual(gw.read_judilibre('dddddddddd05', B)['set_aside_by'], [])
        self.assertIn('refusal', gw.read_judilibre('dddddddddd06', B)); self.assertEqual(gw.read_judilibre('dddddddddd09', B)['refusal'], 'not found')
        self.assertIn('expected form', gw.read_judilibre('../x', B)['refusal'])
        a = L.load_anchor(self.tmp.name, 'S1', {}, 'judilibre:dddddddddd01'); a.update(rec=r, origin='record')
        o = L.check_claim({'id': 'A1', 'text': 'x'}, [a], {'as_of': L.day('2023-01-01'), 'order': 'FR-JUD', 'T': L.day('2023-06-01'), 'today': L.day('2026-10-28')})
        self.assertEqual([x['result'] for x in o if x['rule'] == 'not_overturned'], ['unsupported'])          # set aside before the question date


class Legifrance(Base):
    V1 = {'id': 'LEGIARTI000006438819', 'etat': 'MODIFIE', 'dateDebut': ms('1804-02-19', paris=False), 'dateFin': ms('2016-10-01')}
    V2 = {'id': 'LEGIARTI000032041559', 'etat': 'VIGUEUR', 'dateDebut': ms('2016-10-01'), 'dateFin': 32472144000000}
    TT = [{'id': 'LEGITEXT000006070721', 'cid': 'LEGITEXT000006070721', 'titre': 'Code civil'}]

    def article(self, v, text):
        return {'article': dict(v, num='1382', texte=text, textTitles=self.TT, articleVersions=[self.V1, self.V2])}

    def api(self, m, u, h, b):
        p = json.loads(b) if b else {}
        if u.endswith('consult/getArticle'):
            if p['id'] == self.V1['id']: return 200, self.article(self.V1, 'Tout fait quelconque de l homme, qui cause a autrui un dommage...')
            if p['id'] == self.V2['id']: return 200, self.article(self.V2, 'Les presomptions qui ne sont point etablies par la loi...')
            if p['id'] == 'LEGIARTI000000000009': return 200, {'article': {'id': p['id'], 'num': '9', 'etat': 'ABROGE', 'dateDebut': ms('2000-01-01'), 'dateFin': ms('2010-01-01'),
                                                                            'texte': 'Old rule.', 'textTitles': [{'id': 'LEGITEXT000000000001', 'titre': 'Decret n 99-1'}]}}
            if p['id'] == 'LEGIARTI000000000010': return 200, {'article': {'id': p['id'], 'num': '10', 'etat': 'VIGUEUR', 'dateDebut': ms('2030-01-01'), 'dateFin': 32472144000000}}
            return 200, {'article': None}
        if u.endswith('/search'):
            self.payloads.append(p)
            if p['fond'] == 'JORF':
                return 200, {'totalResultNumber': 2, 'results': [
                    {'titles': [{'id': 'JORFTEXT000000000001', 'title': 'Loi n 2019-1 du 2 janvier 2019'}], 'dateSignature': '2019-01-02', 'datePublication': '2019-01-03'},
                    {'titles': [{'id': 'JORFTEXT000000000002', 'title': 'Loi n 2019-2'}], 'dateSignature': '2019-05-30', 'datePublication': '2019-06-02'}]}
            ex = [{'id': 'LEGIARTI0000000000%02d' % i, 'num': str(i), 'legalStatus': 'VIGUEUR', 'dateDebut': d, 'dateFin': 32472144000000, 'type': 'articles'}
                  for i, d in ((1, ms('2019-05-31')), (2, ms('2019-06-01')), (3, ms('2019-07-01')), (4, None), (5, '2018'), (6, ms('2001-01-01')))]
            ex.append({'id': 'LEGIARTI000000000007', 'num': '7', 'legalStatus': 'ABROGE', 'dateDebut': ms('2001-01-01'), 'dateFin': ms('2025-01-01'), 'type': 'articles'})
            return 200, {'totalResultNumber': 7, 'results': [{'titles': [{'id': 'LEGITEXT000006070721', 'title': 'Code civil'}], 'sections': [{'extracts': ex}]}] if p['fond'] == 'CODE_DATE' else []}
        return 404, {}

    def setUp(self): super().setUp(); self.keys(); self.payloads = []; self.s = self.stub(self.api)

    def test_dates(self):
        self.assertEqual(gw.lf_day(ms('2016-10-01')), '2016-10-01'); self.assertEqual(gw.lf_day(ms('2016-10-01', paris=False)), '2016-10-01'); self.assertEqual(gw.lf_day(ms('2016-10-01', paris=False) + 43200000), '2016-10-01')
        self.assertEqual(gw.lf_day(32472144000000), '2999-01-01'); self.assertEqual(gw.lf_day('2016-10-01T00:00:00.000+0000'), '2016-10-01'); self.assertIsNone(gw.lf_day(None))

    def test_barrier_search(self):
        B = gw.Barrier('2019-06-01', forbidden_dois=['LEGIARTI000000000006'])
        out, tot = gw.search_legifrance('article 1382 responsabilite', 20, B)
        self.assertEqual([o['id'] for o in out], ['legi:LEGIARTI000000000001', 'legi:LEGIARTI000000000005', 'legi:LEGIARTI000000000007'])
        self.assertEqual(B.excluded, 4)                                                                       # day T, after T, no date, forbidden id
        a7 = out[2]; self.assertEqual((a7['valid_until'], a7['legi_state']), (None, 'VIGUEUR')); self.assertIn('masked', a7['validity'])   # end after T masked
        self.assertEqual((out[0]['valid_until'], out[0]['valid_until_exclusive'], out[0]['access'], out[0]['order']), ('2999-01-01', True, 'api', 'FR'))
        p = self.payloads[0]; self.assertEqual([x['fond'] for x in self.payloads], ['CODE_DATE', 'LODA_DATE'])
        f = p['recherche']['filtres'][0]; self.assertEqual(f['facette'], 'DATE_VERSION'); self.assertEqual(gw.lf_day(f['singleDate']), '2019-05-31')
        ch = {c['typeChamp']: c['criteres'][0] for c in p['recherche']['champs']}
        self.assertEqual((ch['NUM_ARTICLE']['valeur'], ch['NUM_ARTICLE']['typeRecherche'], ch['ALL']['valeur']), ('1382', 'EXACTE', 'responsabilite'))
        self.assertIn('version in force on 2019-05-31', tot)
        B = gw.Barrier('2019-06-01', forbidden_titles=['Loi n 2019-1 du 2 janvier 2019'])
        self.assertEqual(gw.search_legifrance('loi', 10, B, fund='jorf')[0], [])                           # forbidden title; the other published on/after T
        self.assertEqual(B.excluded, 2)
        self.assertEqual([x['facette'] for x in self.payloads[-1]['recherche']['filtres']], ['DATE_PUBLICATION', 'DATE_SIGNATURE'])
        self.assertEqual(self.payloads[-1]['recherche']['filtres'][0]['dates']['end'], '2019-05-31')
        out = gw.search_legifrance('loi', 10, gw.Barrier('2019-06-03'), fund='jorf')[0]
        self.assertEqual([(o['id'], o['date'], o['date_published']) for o in out], [('jorf:JORFTEXT000000000001', '2019-01-02', '2019-01-03'), ('jorf:JORFTEXT000000000002', '2019-05-30', '2019-06-02')])
        self.assertIn('fund', gw.search_legifrance('x', 5, B, fund='kali')[1])

    def test_version_on_the_eve_and_exclusive_end(self):
        r = gw.read_legi('LEGIARTI000006438819', gw.Barrier('2016-10-02'))                           # eve 2016-10-01: the new version
        self.assertEqual((r['version'], r['valid_from'], r['legi_state'], r['id']), (self.V2['id'], '2016-10-01', 'VIGUEUR', 'legi:LEGIARTI000006438819'))
        self.assertIn('presomptions', r['abstract']); self.assertEqual(r['version_requested'], 'LEGIARTI000006438819')
        r = gw.read_legi('LEGIARTI000032041559', gw.Barrier('2016-10-01'))                           # eve 2016-09-30: old 1382 (end 2016-10-01 exclusive, on T: masked)
        self.assertEqual((r['version'], r['valid_until'], r['legi_state'], r['in_force_on_eve_of_T']), (self.V1['id'], None, 'VIGUEUR', True))
        self.assertIn('Tout fait quelconque', r['abstract']); self.assertEqual([v['id'] for v in r['versions_before_T']], [self.V1['id']])
        r = gw.read_legi('LEGIARTI000006438819', gw.Barrier('2016-10-03'))
        self.assertEqual(r['versions_before_T'][0]['valid_until'], '2016-10-01')                      # end before T: served
        bodies = [json.loads(c['body']) for c in self.s.calls if c['url'].endswith('getArticle')]
        self.assertEqual(bodies[:2], [{'id': 'LEGIARTI000006438819'}, {'id': self.V2['id']}])       # the version picked is re-read by its own id
        r = gw.read_legi('LEGIARTI000000000009', gw.Barrier('2015-06-01'))                           # abrogated before T: last version, end served
        self.assertEqual((r['valid_until'], r['legi_state'], r['in_force_on_eve_of_T']), ('2010-01-01', 'ABROGE', False))
        self.assertIn('after T', gw.read_legi('LEGIARTI000000000010', gw.Barrier('2020-01-01'))['refusal'])
        self.assertIn('refusal', gw.read_legi('LEGIARTI000006438819', gw.Barrier('1804-02-19')))     # first version starts on T
        self.assertIn('expected form', gw.read_legi('LEGIARTI1', gw.Barrier('2020-01-01'))['refusal'])
        self.assertEqual(gw.read_legi('LEGIARTI000000000099', gw.Barrier('2020-01-01'))['refusal'], 'not found')

    def test_law_checks_on_a_legifrance_record(self):
        d = pathlib.Path(self.tmp.name) / 'run'; d.mkdir()
        (d / 'card.json').write_text(json.dumps({'card_id': 'c', 'order': 'FR', 'sources': {'S1': {'legi': 'LEGIARTI000000000009', 'title': 'Decret n 99-1, article 9'}},
                                                 'claims': [{'id': 'A1', 'text': 'Article 9 of the decree requires a prior declaration.', 'source': {'key': 'S1'}},
                                                            {'id': 'A2', 'text': 'Article 9 of the decree was repealed with effect from 1 January 2010.', 'source': {'key': 'S1'}}]}))
        (d / 'verdicts.json').write_text(json.dumps({'claims': [{'id': 'A1', 'status': 'FOUND'}, {'id': 'A2', 'status': 'FOUND'}]}))
        g = self.gateway('2015-06-01')
        out = L.check_run(d, as_of='2015-06-01', fetch=True, T='2015-06-01', gateway=g, today='2026-10-28')
        self.assertEqual(out['fetch']['fetched'], 1); c = {x['id']: x for x in out['claims']}
        self.assertEqual(c['A1']['final_status'], 'DISTORTED'); self.assertIn('exclusive', c['A1']['discrepancy'])
        self.assertEqual(c['A2']['final_status'], 'FOUND')                                                    # a claim about its repeal is not penalised
        r = {x['rule']: x['result'] for x in c['A2']['rules']}
        self.assertEqual((r['resolves'], r['in_force_at_date'], r['version_pinned'], r['jurisdiction_match']), ('supported', 'supported', 'supported', 'supported'))
        self.assertTrue(L.well_formed('legi:LEGITEXT000006070721') and L.well_formed('jorf:JORFTEXT000032004939') and L.well_formed('judilibre:5fca56cd0a790c1ec36ddc07'))
        self.assertFalse(L.well_formed('legi:LEGIARTI12'))
        self.no_leak(out)


if __name__ == '__main__':
    unittest.main()
