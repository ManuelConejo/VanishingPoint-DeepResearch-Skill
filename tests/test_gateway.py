#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Non-retrievability test of gateway.py (19 admissible date-barrier cases from tests/fixtures/bench_cases.json)
+ arXiv, plugin `sources` block, undeclared engines, cap. Everything offline (fetch replaced).
Online (--online): the exact title of each review searched on the 4 engines + read of its DOI; the review must stay unfindable.
Run: python3 -I tests/test_gateway.py
"""
import datetime as dt, json, os, pathlib, re, sys, tempfile, unittest, urllib.parse
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import gateway as gw

CASE_TABLE = json.loads((P / 'fixtures' / 'bench_cases.json').read_text())
CASES = list(CASE_TABLE)


def scenario(case):
    c = CASE_TABLE[case]; T = dt.date.fromisoformat(c['T'][:10])
    v, f = (T - dt.timedelta(days=1)).isoformat(), (T + dt.timedelta(days=1)).isoformat()
    review_title = c['forbidden_titles'][0]
    docs = [  # (doi, title, date_published, date_indexed, expected_visible)
        (c['forbidden_dois'][0], 'Neutral title', v, v, False),       # DOI of the review with old dates
        ('10.1/copy', review_title, v, v, False),                       # title of the review under another DOI
        ('10.1/copy2', review_title.upper() + ': a systematic review', v, v, False),
        ('10.1/future', 'Future', f, v, False), ('10.1/deposit', 'Late deposit', v, f, False),
        ('10.1/dayT', 'Day T', T.isoformat(), v, False), ('10.1/partial', 'Partial', str(T.year), v, False),
        ('10.1/old', 'Old relevant', v, v, True)]
    return T, docs


def atom(docs, v1=False):
    e = ''.join(f'<entry><id>http://arxiv.org/abs/2401.0000{i}v2</id><updated>{d[2] if v1 else d[3]}T00:00:00Z</updated><published>{d[2]}T00:00:00Z</published>'
                f'<title>{d[1]}</title><summary>ABSTRACT</summary><author><name>A. Author</name></author><arxiv:doi>{d[0]}</arxiv:doi></entry>' for i, d in enumerate(docs))
    return (f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom" '
            f'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"><opensearch:totalResults>{len(docs)}</opensearch:totalResults>{e}</feed>').encode()


def fake_fetch(docs, T):
    def fetch(url):
        u = urllib.parse.unquote(url)
        if 'export.arxiv.org' in u:
            if 'id_list=' in u:
                aid = u.split('id_list=')[1].split('&')[0]; i = int(re.search(r'2401\.0000(\d)', aid).group(1))
                assert aid.endswith('v1'), aid                                 # read always asks for v1
                return atom([docs[i]], v1=True)                                # v1: updated = published
            return atom(docs)
        if 'esearch.fcgi' in u: return json.dumps({'esearchresult': {'count': len(docs), 'idlist': [str(i) for i in range(len(docs))]}}).encode()
        if 'esummary.fcgi' in u:
            ids = u.split('id=')[-1].split(',')
            return json.dumps({'result': {i: {'title': docs[int(i)][1], 'articleids': [{'idtype': 'doi', 'value': docs[int(i)][0]}],
                                              'history': [{'pubstatus': 'entrez', 'date': docs[int(i)][3]}], 'epubdate': docs[int(i)][2],
                                              'sortpubdate': docs[int(i)][2], 'pubdate': docs[int(i)][2]} for i in ids}}).encode()
        if 'efetch.fcgi' in u: return b'ABSTRACT'
        if 'europepmc' in u and ('/citations?' in u or '/references?' in u):
            L = [{'id': str(1000 + i), 'source': 'MED', 'title': d[1], 'pubYear': d[2][:4], 'doi': d[0]} for i, d in enumerate(docs)]
            L += [{'source': 'AGR', 'title': d[1], 'pubYear': d[2][:4], 'doi': d[0]} for d in docs if d[0] in (docs[0][0], '10.1/copy', '10.1/copy2', '10.1/future', '10.1/dayT', '10.1/partial')]
            L += [{'source': 'AGR', 'title': 'Old without PMID', 'pubYear': str(int(docs[-1][2][:4]) - 1), 'doi': '10.1/old/noid'}]
            return json.dumps({'citationList': {'citation': L}, 'referenceList': {'reference': L}}).encode()
        if 'europepmc' in u:
            res = [{'id': str(1000 + i), 'source': 'MED', 'pmid': str(1000 + i), 'doi': d[0], 'title': d[1], 'firstIndexDate': d[3], 'firstPublicationDate': d[2],
                    'pubYear': d[2][:4], 'abstractText': 'ABSTRACT'} for i, d in enumerate(docs)]
            if 'DOI:"' in u:
                doi = u.split('DOI:"')[1].split('"')[0]; res = [r for r in res if r['doi'] == doi]
            return json.dumps({'hitCount': len(res), 'resultList': {'result': res}}).encode()
        if 'opencitations' in u:
            return json.dumps([{'citing': f'omid:x doi:{d[0]}', 'creation': d[2]} for d in docs]).encode()
        if 'crossref' in u and '/works/' in u and 'works?' not in u:
            doi = u.split('/works/')[1].split('?')[0]
            d = next(x for x in docs if x[0] == doi)
            refs = [{'DOI': x[0]} for x in docs] + [{'unstructured': x[1], 'year': x[2][:4]} for x in docs if x[0] in ('10.1/copy', '10.1/copy2', '10.1/future', '10.1/dayT')]
            return json.dumps({'message': {'DOI': d[0], 'title': [d[1]], 'issued': {'date-parts': [[int(y) for y in d[2].split('-')]]}, 'created': {'date-time': d[3] + 'T00:00:00Z'}, 'reference': refs}}).encode()
        if 'crossref' in u:
            its = [{'DOI': d[0], 'title': [d[1]], 'issued': {'date-parts': [[int(x) for x in d[2].split('-')]]},
                    'created': {'date-time': d[3] + 'T00:00:00Z'}} for d in docs]
            return json.dumps({'message': {'items': its, 'total-results': len(its)}}).encode()
        if 'openalex' in u:
            ws = [{'id': f'https://openalex.org/W{i}', 'doi': 'https://doi.org/' + d[0], 'title': d[1], 'publication_date': d[2],
                   'publication_year': int(d[2][:4]), 'referenced_works': [f'W{j}' for j in range(len(docs))],
                   'abstract_inverted_index': {'ABSTRACT': [0]}} for i, d in enumerate(docs)]
            if '/works/doi:' in u:
                doi = u.split('/works/doi:')[1].split('?')[0]
                return json.dumps(next((w for w in ws if w['doi'].endswith(doi)), ws[-1])).encode()
            if '/works/W' in u: return json.dumps(ws[-1]).encode()
            return json.dumps({'results': ws, 'meta': {'count': len(ws)}}).encode()
        raise AssertionError('unexpected URL ' + url)
    return fetch


class Offline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); gw.STATE = pathlib.Path(self.tmp.name)
        self.fetch0 = gw.fetch

    def tearDown(self):
        gw.fetch = self.fetch0; self.tmp.cleanup()

    def test_19_cases_all_engines(self):
        self.assertEqual(len(CASES), 19)
        for case in CASES:
            with self.subTest(case=case):
                T, docs = scenario(case); gw.fetch = fake_fetch(docs, T); B = gw.Barrier.from_case(case)
                for fn in (gw.search_pubmed, gw.search_europepmc, gw.search_crossref, gw.search_openalex, gw.search_arxiv):
                    out, _ = fn('recognisable query', 20, B)
                    dois = {(o.get('doi') or o['id'].replace('doi:', '')).lower() for o in out}
                    self.assertEqual(dois, {'10.1/old'}, (fn.__name__, dois))
                for fn in (gw.citing, gw.references):
                    out, _ = fn('doi:10.1/old', 50, B)
                    ok = {(o.get('doi') or o['id'].replace('doi:', '')).lower() for o in out}
                    self.assertTrue(ok <= {'10.1/old', '10.1/old/noid'} and ok, (fn.__name__, ok))
                # OpenAlex fallback (chaining) when Europe PMC ignores the document
                f0 = gw.fetch
                gw.fetch = lambda u: (json.dumps({'hitCount': 0, 'resultList': {'result': []}}).encode() if 'europepmc' in urllib.parse.unquote(u) and 'search?' in u else f0(u))
                for fn in (gw.citing, gw.references):
                    out, _ = fn('doi:10.1/old', 50, B)
                    self.assertEqual({o['id'] for o in out}, {'doi:10.1/old'}, ('fallback', fn.__name__))
                # OpenAlex fallback (OpenCitations and Crossref silent)
                f1 = gw.fetch
                gw.fetch = lambda u: (b'[]' if 'opencitations' in u else json.dumps({'message': {'DOI': '10.1/old', 'title': ['Old relevant'], 'issued': {'date-parts': [[int(y) for y in docs[-1][2].split('-')]]}, 'created': {'date-time': docs[-1][3] + 'T00:00:00Z'}, 'reference': []}}).encode() if ('crossref' in u and '/works/' in u and 'works?' not in u) else f1(u))
                for fn in (gw.citing, gw.references):
                    out, _ = fn('doi:10.1/old', 50, B)
                    self.assertEqual({o['id'] for o in out}, {'doi:10.1/old'}, ('OpenAlex fallback', fn.__name__))
                gw.fetch = f0
                for d in docs:
                    r = gw.read('doi:' + d[0], B)
                    self.assertEqual('refusal' not in r, d[4], (d[0], r))
                # arXiv: read, citing and references of an arxiv: identifier (after T -> refusal; before -> OpenAlex, Crossref recheck)
                for i, d in enumerate(docs):
                    r = gw.read(f'arxiv:2401.0000{i}', B)                      # v1: visible iff published < T, outside the forbidden review
                    self.assertEqual('refusal' not in r, d[4] or d[0] == '10.1/deposit', ('arxiv', d[0], r))
                for fn in (gw.citing, gw.references):
                    self.assertEqual(fn('arxiv:2401.00003', 50, B)[0], [], ('arxiv future', fn.__name__))
                    self.assertEqual(fn('arxiv:2401.00005', 50, B)[0], [], ('arxiv day T', fn.__name__))
                    self.assertEqual({o['id'] for o in fn('arxiv:2401.00007', 50, B)[0]}, {'doi:10.1/old'}, ('arxiv old', fn.__name__))
                # provider-side filters set on the eve of T
                urls = []
                orig = gw.fetch
                gw.fetch = lambda u: (urls.append(urllib.parse.unquote(u)) or orig(u))
                gw.search_pubmed('x', 5, B); gw.search_europepmc('x', 5, B); gw.search_crossref('x', 5, B); gw.search_openalex('x', 5, B); gw.search_arxiv('x', 5, B)
                eve = T - dt.timedelta(days=1)
                self.assertIn(f'maxdate={eve:%Y/%m/%d}', urls[0]); self.assertIn(f'TO {eve}]', urls[2])
                self.assertIn(f'until-created-date:{eve},until-pub-date:{eve}', urls[3]); self.assertIn(f'to_publication_date:{eve}', urls[4])
                self.assertIn(f'TO+{eve:%Y%m%d}2359]', urls[-1])
                self.assertFalse(any('@' in u for u in urls), 'no e-mail literal in any URL')

    def test_dates(self):
        self.assertEqual(gw.date_upper('2024 Feb'), dt.date(2024, 2, 28)); self.assertEqual(gw.date_upper('2024 Spring'), dt.date(2024, 12, 30))
        self.assertEqual(gw.date_upper('2024/04/12 00:00'), dt.date(2024, 4, 12)); self.assertIsNone(gw.date_upper(''))

    def test_lower_bound(self):
        B = gw.Barrier('2026-01-01', since=2020)
        self.assertFalse(B.ok(None, '2019-05-01')); self.assertTrue(B.ok(None, '2021-05-01')); self.assertFalse(B.ok(None, '2026-01-01'))
        self.assertEqual(B.start, dt.date(2020, 1, 1))

    def test_plugins_and_interface(self):
        T, docs = scenario(CASES[0]); gw.fetch = fake_fetch(docs, T)
        d = pathlib.Path(self.tmp.name)
        (d / 'p1.md').write_text('# Plugin X\n## Sources\n```sources\nengines: openalex, arxiv, github  # github: not wired\nsince: 2015\ncap: 3\nkeys: VP_NONEXISTENT_KEY\n'
                                 'access: openalex=api, arxiv=api, github=api\ndisabled: ssrn=tos_forbidden\n```\n## Biases\n', encoding='utf-8')
        (d / 'p2.md').write_text('# Plugin without block\n## Sources\n- nothing declared\n', encoding='utf-8')
        g = gw.Gateway([d / 'p1.md', d / 'p2.md'], T=T, run='t1', state=d / 'state')
        s = g.sources()
        self.assertEqual(s['engines'], ['arxiv', 'openalex']); self.assertEqual(s['not_wired'], ['github'])
        self.assertEqual(s['cap'], 3); self.assertEqual(s['since'], 2015); self.assertEqual(s['keys_present'], [])
        self.assertEqual([x['sources_block'] for x in s['plugins']], [True, False])
        self.assertEqual(s['bound'], f'documents before {T}')
        self.assertIn('refusal', g.search('pubmed', 'x'))                     # not declared: refused, not counted
        r = g.search('openalex', 'x'); self.assertEqual(r['call'], 1)
        self.assertEqual((r['engine'], r['query'], r['n']), ('openalex', 'x', 20))
        ids = {x['id'] for x in r['results']}                                  # without case: no forbidden DOI, but nothing >= T
        self.assertIn('doi:10.1/old', ids); self.assertFalse(ids & {'doi:10.1/future', 'doi:10.1/deposit', 'doi:10.1/dayT', 'doi:10.1/partial'})
        self.assertEqual(g.read('arxiv:2401.00007')['results']['abstract'], 'ABSTRACT')
        self.assertEqual(g.citing('doi:10.1/old')['call'], 3)
        self.assertIn('CAP', g.references('doi:10.1/old')['refusal'])        # 4th call: cap 3
        lines = [json.loads(x) for x in (d / 'state' / 'journal.jsonl').read_text().splitlines()]
        self.assertEqual(len(lines), 3)
        self.assertEqual([x['call'] for x in lines], ['search-openalex', 'read', 'citing'])
        self.assertTrue({'utc', 'run', 'call', 'engine', 'query', 'n', 'excluded', 'error', 'ids'} <= set(lines[0]))
        q = gw.Gateway([], T=T, run='t2', state=d / 'state')                   # without plugin: every engine, default cap
        self.assertEqual(q.sources()['engines'], sorted(gw.ENGINES)); self.assertEqual(q.cap, gw.CFG['call_cap']['default'])
        self.assertIn('refusal', q.call('whatever', 'x'))
        self.assertEqual(gw.Gateway([], case=CASES[0], state=d / 'state').B.T, T)

    def test_shipped_plugins(self):
        """The shipped plugins in plugins/ all load (sources block present, engines recognised or listed not_wired), offline.
        Skipped when the plugins directory is absent (the gateway does not depend on it)."""
        plugins_dir = P.parent / 'plugins'
        shipped = sorted(x for x in plugins_dir.glob('*.md') if not x.name.startswith('_')) if plugins_dir.is_dir() else []
        if not shipped: self.skipTest('no shipped plugin found')
        T, docs = scenario(CASES[0]); gw.fetch = fake_fetch(docs, T)
        d = pathlib.Path(self.tmp.name)
        self.assertEqual([x.stem for x in shipped], ['biology', 'code', 'cs-ai', 'finance', 'law'])
        for f in shipped:
            with self.subTest(plugin=f.stem):
                p = gw.read_plugin(f)
                self.assertTrue(p['declared'], 'fenced ```sources block absent'); self.assertTrue(p['engines'] or p['code_engines'])
                s = gw.Gateway([f], T=T, run='t-' + f.stem, state=d / 'state').sources()
                self.assertEqual(sorted(s['engines'] + s['not_wired']), sorted(set(p['engines'])))
                for m in s['not_wired']: self.assertIn('refusal', gw.Gateway([f], T=T, run='t-' + f.stem, state=d / 'state').search(m, 'x'))
        every = gw.Gateway(shipped, T=T, run='t-all', state=d / 'state').sources()
        self.assertEqual(every['engines'], sorted(gw.ENGINES)); self.assertEqual(every['cap'], 60)
        template = plugins_dir / '_TEMPLATE.md'
        if template.exists(): self.assertTrue(gw.read_plugin(template)['declared'])   # the template has a block, with engines to fill in


def test_online():
    report = {}
    for case in CASES:
        B = gw.Barrier.from_case(case); title = CASE_TABLE[case]['forbidden_titles'][0]; doi = CASE_TABLE[case]['forbidden_dois'][0].lower()
        res = {}
        for name, fn in [('pubmed', gw.search_pubmed), ('europepmc', gw.search_europepmc), ('crossref', gw.search_crossref), ('openalex', gw.search_openalex)]:
            try:
                out, _ = fn(title, 20, B)
                found = any((o.get('doi') or o['id'].replace('doi:', '')).lower() == doi or gw.title_sim(gw.tokens(o.get('title') or ''), gw.tokens(title)) >= 0.8 for o in out)
                res[name] = {'n': len(out), 'review_found': found}
            except Exception as e:
                res[name] = {'error': str(e)[:80]}
        res['read_review_doi'] = 'refusal' in gw.read('doi:' + doi, B)
        report[case] = res
        ok = all(not v.get('review_found') for v in res.values() if isinstance(v, dict)) and res['read_review_doi']
        print(case, 'OK' if ok else 'FAIL', json.dumps(res, ensure_ascii=False))
    gw.STATE.mkdir(parents=True, exist_ok=True)
    (gw.STATE / 'test-online.json').write_text(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    if '--online' in sys.argv: test_online()
    else: unittest.main()
