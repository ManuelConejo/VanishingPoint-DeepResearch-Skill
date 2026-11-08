#!/usr/bin/env python3
"""Lacuna engine (tools/sources/lacuna.py, plugins/cs-ai.md), offline: recorded Lacuna answers (tests/fixtures/lacuna_*.json, recorded
2026-11-08) with fetch replaced. Date barrier (year-precision records read as a year, day records, month of v1 of the arXiv id, undated ->
refused, provider filter at the eve of T never trusted alone); DOI / arXiv identifiers carried for deduplication and rechecked (Crossref,
arXiv); generated directions and hypotheses never requested nor served without the explicit option, and with it marked
generated_hypothesis / evidence False / never citable; read lacuna:<artifact id>; no key nor e-mail in a URL.
Run: python3 -I tests/test_engines_lacuna.py
"""
import datetime as dt, json, os, pathlib, re, sys, tempfile, unittest, urllib.error, urllib.parse
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import gateway as gw   # noqa: E702
import validate_card as VC, validate_result as VR   # noqa: E402
from sources import lacuna as L   # noqa: E402

FIX = P / 'fixtures'
PAPERS = json.loads((FIX / 'lacuna_search_paper.json').read_text())
HYP = json.loads((FIX / 'lacuna_search_hypothesis.json').read_text())
DIRS = json.loads((FIX / 'lacuna_search_direction.json').read_text())
RECORD = json.loads((FIX / 'lacuna_paper.json').read_text())
T = dt.date(2024, 6, 1)
LATE_DOI = '10.18653/v1/2021.acl-long.316'                         # Crossref says deposited after T in these tests -> refused
DOIS = {'10.18653/v1/2023.emnlp-main.495': ('2023-11-20', '2023-12'), '10.18653/v1/2021.findings-emnlp.232': ('2021-11-01', '2021-11'),
        LATE_DOI: ('2024-07-01', '2021-08')}
KEPT = ['lacuna:art_3c2a82beab2842d7bf71cb4c2f52b26f', 'arxiv:2312.10997', 'doi:10.18653/v1/2023.emnlp-main.495',
        'doi:10.18653/v1/2021.findings-emnlp.232', 'arxiv:2202.01110', 'arxiv:2405.07437', 'arxiv:2401.11391']


def http404(url): return urllib.error.HTTPError(url, 404, 'not found', {}, None)


def crossref(url):
    ds = re.findall(r'doi:([^,&]+)', urllib.parse.unquote(url))
    return {'message': {'items': [{'DOI': d, 'title': ['t'], 'created': {'date-time': DOIS[d][0] + 'T00:00:00Z'},
                                   'issued': {'date-parts': [[int(x) for x in DOIS[d][1].split('-')]]}} for d in ds if d in DOIS]}}


def arxiv_batch(url):
    ids = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['id_list'][0].split(',')
    ent = ''.join(f'<entry><id>http://arxiv.org/abs/{i}v2</id><title>arXiv record {i}</title></entry>' for i in ids)
    return f'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">{ent}</feed>'


def lacuna_search(url):
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    if q.get('offset', ['0'])[0] != '0': return dict(PAPERS, results=[])
    return {'paper': PAPERS, 'hypothesis': HYP, 'cluster': DIRS}[q['type'][0]]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.state0 = gw.STATE; gw.STATE = pathlib.Path(self.tmp.name); self.fetch0 = gw.fetch; self.urls = []
        self.contact = os.environ.get('VP_CONTACT'); os.environ['VP_CONTACT'] = 'someone@example.org'   # must never reach a Lacuna URL
        self.route([(r'lacuna\.tiptreesystems\.com/api/v1/search\?', lacuna_search), (r'lacuna\.tiptreesystems\.com/api/v1/papers/art_', RECORD),
                    (r'api\.crossref\.org/works', crossref), (r'export\.arxiv\.org/api/query\?id_list=', arxiv_batch)])

    def tearDown(self):
        gw.fetch = self.fetch0; gw.STATE = self.state0; self.tmp.cleanup()
        if self.contact is None: os.environ.pop('VP_CONTACT', None)
        else: os.environ['VP_CONTACT'] = self.contact

    def route(self, table):
        def fetch(url, headers=None):
            self.urls.append(urllib.parse.unquote_plus(url))
            for pat, ans in table:
                if re.search(pat, url):
                    a = ans(url) if callable(ans) else ans
                    return a.encode() if isinstance(a, str) else json.dumps(a).encode()
            raise http404(url)
        gw.fetch = fetch

    def lacuna_urls(self): return [u for u in self.urls if 'lacuna.tiptreesystems.com' in u]


class Barrier(Base):
    def test_only_records_dated_before_T(self):
        B = gw.Barrier(T)
        out, total = gw.ENGINES['lacuna']('retrieval augmented generation', 20, B)
        self.assertEqual([x['id'] for x in out], KEPT)
        self.assertEqual(total, PAPERS['total_results'])
        self.assertGreaterEqual(B.excluded, 20 - len(KEPT))         # 12 dated on/after T (year of T at year precision included) + 1 late DOI
                                                                     # (crossref_deposit counts a refused DOI in cr_item and again in its total)
        for x in out:
            self.assertEqual((x['type'], x['tier']), ('paper', 'index'))
            self.assertLess(int(x['year']), T.year + (1 if x['id'].startswith('arxiv:') else 0))
            if x['id'].startswith('arxiv:'): self.assertLess(gw.date_upper(gw.arxiv_month(x['arxiv'])), T)

    def test_provider_filter_at_eve_of_T_and_no_contact_in_url(self):
        B = gw.Barrier(T, since=2020)
        gw.ENGINES['lacuna']('retrieval augmented generation', 20, B)
        first = self.lacuna_urls()[0]
        self.assertIn('type=paper', first); self.assertIn('date_to=2024-05-31', first); self.assertIn('date_from=2020-01-01', first)
        for u in self.lacuna_urls(): self.assertFalse('@' in u or re.search(r'api_key|token|mailto', u, re.I), u)
        self.assertEqual(gw.INTERVAL['lacuna.tiptreesystems.com'], max(1.0, gw.CFG['lacuna']['interval_s']))
        self.assertGreaterEqual(gw.INTERVAL['lacuna.tiptreesystems.com'], 1.0)

    def test_year_precision_is_a_year_never_1_january(self):
        B = gw.Barrier('2024-03-01')                                 # RAGAs: published_date 2024-01-01, date_precision year
        r = next(x for x in PAPERS['results'] if x['title'].startswith('RAGAs'))
        self.assertIsNone(L.lc_item(r, B))
        self.assertIsNotNone(L.lc_item(r, gw.Barrier('2025-01-01')))
        self.assertIsNone(L.lc_item(dict(r, date_precision=None), B))   # no precision and 1 January -> still a year

    def test_undated_or_forbidden_refused(self):
        r = next(x for x in PAPERS['results'] if x['title'].startswith('A Survey on Retrieval-Augmented Text'))
        B = gw.Barrier(T)
        self.assertIsNotNone(L.lc_item(r, B))
        self.assertIsNone(L.lc_item(dict(r, published_date=None, date_precision=None), B))   # a bare year field is not enough
        self.assertIsNone(L.lc_item(r, gw.Barrier(T, forbidden_dois=['10.48550/arXiv.2202.01110'])))
        self.assertIsNone(L.lc_item(r, gw.Barrier(T, forbidden_titles=[r['title']])))
        self.assertIsNone(L.lc_item(dict(r, published_date='2022-02-02', identifiers={'arxiv_id': '2207.00001'}), B) and None)
        self.assertIsNone(L.lc_item(dict(r, identifiers={'arxiv_id': '2406.00001'}), B))       # v1 month (2024-06) not before T


class Identifiers(Base):
    def test_doi_and_arxiv_carried_for_dedup(self):
        out, _ = gw.ENGINES['lacuna']('retrieval augmented generation', 20, gw.Barrier(T))
        by = {x['id']: x for x in out}
        self.assertNotIn('doi', by['arxiv:2405.07437'])              # arXiv DOI 10.48550/arXiv.<id> folded into the arXiv id
        self.assertEqual(by['arxiv:2312.10997']['arxiv'], '2312.10997')   # arXiv id read from an arxiv.org PDF link (version dropped)
        self.assertEqual(by['doi:10.18653/v1/2023.emnlp-main.495']['dblp'], 'conf/emnlp/JiangXGSLDYCN23')
        self.assertEqual(by['lacuna:art_3c2a82beab2842d7bf71cb4c2f52b26f']['openreview'], 'HHHbqJBP0b5')
        other = ['arxiv:2405.07437', 'doi:10.48550/arXiv.2312.10997v5', 'DOI:10.18653/V1/2023.EMNLP-MAIN.495', 'arxiv:2501.00001']   # another engine
        seen = set().union(*(gw.id_forms(i) for i in other))
        exclusive = [x['id'] for x in out if not gw.id_forms(x['id']) & seen]
        self.assertEqual(exclusive, [i for i in KEPT if i not in ('arxiv:2405.07437', 'arxiv:2312.10997', 'doi:10.18653/v1/2023.emnlp-main.495')])
        for i in KEPT: self.assertTrue(VR.ID.match(i), i)           # every served id is a result.json identifier

    def test_doi_and_arxiv_rechecked(self):
        gw.ENGINES['lacuna']('retrieval augmented generation', 20, gw.Barrier(T))
        self.assertTrue(any('api.crossref.org' in u and LATE_DOI in u for u in self.urls))
        self.assertTrue(any('export.arxiv.org' in u and '2405.07437' in u for u in self.urls))
        self.route([(r'lacuna\.tiptreesystems\.com/api/v1/search\?', lacuna_search), (r'api\.crossref\.org/works', crossref)])   # arXiv down
        out, _ = gw.ENGINES['lacuna']('retrieval augmented generation', 20, gw.Barrier(T))
        self.assertFalse([x for x in out if x['id'].startswith('arxiv:')])   # strict: an arXiv id not attested is refused


class Generated(Base):
    def test_never_requested_nor_served_by_default(self):
        out, _ = gw.ENGINES['lacuna']('retrieval augmented generation', 20, gw.Barrier(T))
        self.assertTrue(all('type=paper' in u for u in self.lacuna_urls() if '/search?' in u))
        self.assertFalse([x for x in out if x.get('type') == 'generated_hypothesis' or x['id'].startswith('lacunaidea:')])

    def test_explicit_option_marks_leads(self):
        for kind, fix in (('hypothesis', HYP), ('direction', DIRS)):
            out, _ = gw.ENGINES['lacuna']('retrieval augmented generation', 5, gw.Barrier(T), generated=kind)
            self.assertEqual(len(out), len(fix['results']))
            for x in out:
                self.assertEqual((x['type'], x['evidence'], x['kind'], x['dating']), ('generated_hypothesis', False, kind, 'absent'))
                self.assertTrue(x['id'].startswith(f'lacunaidea:{kind}/') and x['leak_risk'] and x['url'].startswith('https://'))
        self.assertTrue(any('type=cluster' in u for u in self.lacuna_urls()))
        out, _ = gw.ENGINES['lacuna']('q', 5, gw.Barrier(T), generated='paper')
        self.assertIn('refusal', out)

    def test_leads_are_never_citable(self):
        out, _ = gw.ENGINES['lacuna']('retrieval augmented generation', 5, gw.Barrier(T), generated='hypothesis')
        self.assertNotIn('lacunaidea', VC.IDS)                       # not a card identifier field
        self.assertFalse(VR.ID.match(out[0]['id']))                  # not a result.json identifier
        self.assertIn('refusal', gw.read(out[0]['id'], gw.Barrier(T)))
        B = gw.Barrier(T, forbidden_titles=[HYP['results'][0]['title']])
        out, _ = gw.ENGINES['lacuna']('retrieval augmented generation', 5, B, generated='hypothesis')
        self.assertNotIn(HYP['results'][0]['title'], [x['title'] for x in out]); self.assertEqual(B.excluded, 1)

    def test_gateway_option_explicit_and_journaled(self):
        g = gw.Gateway(['cs-ai'], T=T.isoformat(), state=self.tmp.name, run='lac')
        self.assertIn('lacuna', g.engines)
        a = g.search('lacuna', 'retrieval augmented generation', n=5)
        self.assertFalse([x for x in a['results'] if x.get('evidence') is False])
        b = g.search('lacuna', 'retrieval augmented generation', n=5, generated='hypothesis')
        self.assertTrue(b['results'] and all(x['evidence'] is False for x in b['results']))
        self.assertEqual(b['filters'], {'generated': 'hypothesis'})
        j = [json.loads(x) for x in (pathlib.Path(self.tmp.name) / 'journal.jsonl').read_text().splitlines()]
        self.assertEqual([x.get('filters') for x in j], [None, {'generated': 'hypothesis'}])


class Read(Base):
    def test_read_record(self):
        r = gw.read('lacuna:art_3c2a82beab2842d7bf71cb4c2f52b26f', gw.Barrier('2021-01-01'))
        self.assertEqual(r['id'], 'lacuna:art_3c2a82beab2842d7bf71cb4c2f52b26f'); self.assertTrue(r['abstract'].startswith('Large pre-trained'))
        self.assertEqual(r['dblp'], 'conf/nips/LewisPPPKGKLYR020'); self.assertEqual(r['openreview'], 'HHHbqJBP0b5')
        self.assertNotIn('summary_markdown', r)
        self.assertIn('refusal', gw.read('lacuna:art_3c2a82beab2842d7bf71cb4c2f52b26f', gw.Barrier('2020-06-01')))   # year 2020 = year of T
        self.assertIn('refusal', gw.read('lacuna:not-an-id', gw.Barrier('2021-01-01')))


if __name__ == '__main__':
    unittest.main()
