#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""arXiv-only works on the OpenAlex lane (2026-10-31). An arXiv work carries a DataCite DOI (10.48550/arXiv.<id>) or no DOI at all, never a
Crossref DOI: the Crossref deposit recheck used to refuse it, so search-openalex, references / citing / related (OpenAlex chaining) lost every
arXiv-only paper (measured live on 2026-10-31: 7 of the 25 first OpenAlex results for "chain-of-thought prompting reasoning language models",
among them arXiv 2201.11903 and 2203.11171). Now such a work is served as arxiv:<id>, dated by its OpenAlex publication date AND the month
of v1 encoded in the identifier (the rule dblp already applies to CoRR records); doi:10.48550/arXiv.<id> and arxiv:<id> name the same work
(read, chaining, duplicate check of result.json). Everything offline (fetch replaced).
Run: python3 -I tests/test_arxiv_only.py"""
import datetime as dt, json, pathlib, re, sys, tempfile, unittest, urllib.error, urllib.parse
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import gateway as gw, validate_result as VR   # noqa: E702
import sources._common as C   # noqa: E402

T = dt.date(2024, 3, 15); V, F = '2024-03-14', '2024-03-16'
FORBIDDEN_AX = '2401.99999'


def barrier(): return gw.Barrier(T, forbidden_dois=['10.1/forbid', '10.48550/arxiv.' + FORBIDDEN_AX], forbidden_titles=[])


def oa(i, date, doi=None, landing=None, title=None):
    return {'id': 'https://openalex.org/' + i, 'doi': 'https://doi.org/' + doi if doi else None, 'title': title or 'Work ' + i,
            'publication_date': date, 'publication_year': int(date[:4]), 'type': 'preprint' if landing or (doi or '').startswith('10.48550') else 'article',
            'primary_location': {'landing_page_url': landing, 'source': {'display_name': 'arXiv (Cornell University)' if landing else 'J'}}}


# OpenAlex page: journal DOI (Crossref attests it), arXiv DataCite DOI (mixed case as OpenAlex serves it), arXiv landing page without DOI,
# arXiv id whose month of v1 is the month of T (upper bound >= T), forbidden arXiv DOI, OpenAlex date after T, no DOI and no arXiv page.
WORKS = [oa('W1', '2023-01-02', '10.1/j1'), oa('W2', '2023-01-05', '10.48550/arXiv.2301.00001'),
         oa('W3', '2023-02-07', None, 'http://arxiv.org/abs/2302.00002v3'), oa('W4', '2024-03-01', '10.48550/arxiv.2403.00004'),
         oa('W5', '2024-01-10', '10.48550/arxiv.' + FORBIDDEN_AX), oa('W6', F, '10.48550/arxiv.2402.00006'), oa('W7', '2023-01-01'),
         oa('W8', '1999-01-10', None, 'https://arxiv.org/abs/hep-th/9901001')]
KEPT = ['doi:10.1/j1', 'arxiv:2301.00001', 'arxiv:2302.00002', 'arxiv:hep-th/9901001']


def atom(aid, published, updated=None, title='A survey of widgets'):
    return (f'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom"><entry><id>http://arxiv.org/abs/{aid}v1</id>'
            f'<published>{published}T00:00:00Z</published><updated>{updated or published}T00:00:00Z</updated><title>{title}</title>'
            f'<summary>We survey widgets.</summary><author><name>Ada Lovelace</name></author></entry></feed>')


def arxiv_batch(venue=None, missing=()):
    """arXiv answer to the id_list batch of arxiv_recheck: one entry per listed id (minus `missing`), <arxiv:doi> from `venue` (id -> DOI)."""
    def answer(url):
        ids = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['id_list'][0].split(',')
        ent = ''.join(f'<entry><id>http://arxiv.org/abs/{i}v2</id><title>arXiv record {i}</title>'
                      + (f'<arxiv:doi>{(venue or {})[i]}</arxiv:doi>' if i in (venue or {}) else '') + '</entry>' for i in ids if i not in missing)
        return f'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">{ent}</feed>'
    return answer


ARXIV_BATCH = r'export\.arxiv\.org/api/query\?id_list=[^&]*&max_results='


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.state0 = gw.STATE; gw.STATE = pathlib.Path(self.tmp.name); self.fetch0 = gw.fetch; self.urls = []

    def tearDown(self):
        gw.fetch = self.fetch0; gw.STATE = self.state0; self.tmp.cleanup()

    def route(self, table):
        def fetch(url, headers=None):
            self.urls.append(urllib.parse.unquote_plus(url))
            for pat, ans in table:
                if re.search(pat, url):
                    a = ans(url) if callable(ans) else ans
                    return a if isinstance(a, bytes) else (a if isinstance(a, str) else json.dumps(a)).encode()
            raise urllib.error.HTTPError(url, 404, 'not found', {}, None)
        gw.fetch = fetch

    def table(self, seed=None):
        def batch(url):
            u = urllib.parse.unquote(url)
            m = re.search(r'openalex_id:([\w|]+)', u)
            ws = [w for w in WORKS if w['id'].rsplit('/', 1)[-1] in m.group(1).split('|')] if m else WORKS
            return {'meta': {'count': len(ws)}, 'results': ws}
        def crossref(url):
            ds = re.findall(r'doi:([^,&]+)', urllib.parse.unquote(url))
            return {'message': {'items': [{'DOI': d, 'title': ['t'], 'created': {'date-time': '2023-01-02T00:00:00Z'}, 'issued': {'date-parts': [[2023, 1, 2]]}}
                                          for d in ds if d == '10.1/j1']}}
        seed = seed or dict(oa('W0', '2023-06-01', '10.48550/arxiv.2306.00010'), referenced_works=[w['id'] for w in WORKS], related_works=[w['id'] for w in WORKS])
        return [(ARXIV_BATCH, arxiv_batch()), (r'export\.arxiv\.org.*2306\.00010', atom('2306.00010', '2023-06-01')), (r'export\.arxiv\.org.*2301\.00001', atom('2301.00001', '2023-01-05')),
                (r'api\.openalex\.org/works/doi:10\.48550', seed), (r'api\.openalex\.org/works\?', batch), (r'api\.crossref\.org/works\?', crossref)]

    def crossref_dois(self):
        return [d for u in self.urls if 'api.crossref.org' in u for d in re.findall(r'doi:([^,&]+)', u)]


class Helpers(unittest.TestCase):
    def test_arxiv_id(self):
        for s, want in [('10.48550/arXiv.2301.00001', '2301.00001'), ('https://doi.org/10.48550/ARXIV.2301.00001v2', '2301.00001'),
                        ('doi:10.48550/arxiv.hep-th/9901001', 'hep-th/9901001'), ('arxiv:2301.00001v1', '2301.00001'), ('arXiv:1706.03762', '1706.03762'),
                        ('http://arxiv.org/abs/2302.00002v3', '2302.00002'), ('https://arxiv.org/pdf/2302.00002v1.pdf', '2302.00002'),
                        ('10.1/j1', None), ('', None), (None, None), ('10.48550/arxiv.not-an-id', None), ('https://example.org/abs/2301.00001', None)]:
            self.assertEqual(C.arxiv_id(s), want, s)

    def test_arxiv_month(self):
        self.assertEqual((C.arxiv_month('2401.01234'), C.arxiv_month('cs/0101001'), C.arxiv_month('hep-th/9901001'), C.arxiv_month('x')),
                         ('2024-01', '2001-01', '1999-01', None))


class OpenAlexLane(Base):
    def test_search_keeps_arxiv_only(self):
        self.route(self.table()); B = barrier()
        out, _ = gw.search_openalex('widgets', 8, B)
        self.assertEqual([o['id'] for o in out], KEPT)
        self.assertEqual(B.excluded, 4)                                    # W4 month of T, W5 forbidden, W6 after T, W7 undatable
        self.assertEqual(out[1]['arxiv'], '2301.00001')
        self.assertFalse([d for d in self.crossref_dois() if d.lower().startswith('10.48550')])   # arXiv DOIs never sent to Crossref

    def test_references_citing_related_of_arxiv(self):
        for ident in ('arxiv:2306.00010', 'doi:10.48550/arXiv.2306.00010'):
            self.route(self.table())
            out, _ = gw.references(ident, 50, barrier()); self.assertEqual([o['id'] for o in out], KEPT, ident)
            out, _ = gw.related(ident, 50, barrier()); self.assertEqual([o['id'] for o in out], KEPT, ident)
            out, _ = gw.citing(ident, 50, barrier()); self.assertEqual([o['id'] for o in out], KEPT, ident)
            self.assertTrue(any('export.arxiv.org' in u and '2306.00010' in u for u in self.urls), ident)   # the seed is dated by its v1

    def test_arxiv_doi_seed_after_T_refused(self):
        self.route([(r'export\.arxiv\.org', atom('2403.00099', F))] + self.table())
        for f in (gw.references, gw.related, gw.citing):
            self.assertEqual(f('doi:10.48550/arXiv.2403.00099', 50, barrier())[0], [])


class VenueDoiOfPreprint(Base):
    """Security review of 2026-10-31, item 1: an article forbidden by its journal DOI must not come back as its arXiv preprint (a separate
    OpenAlex work with a 10.48550 DOI and a slightly different title), whether the journal DOI is known to arXiv or to OpenAlex."""
    def page(self, *works):
        return lambda url: {'meta': {'count': len(works)}, 'results': list(works)}

    def test_journal_doi_recorded_by_arxiv(self):
        w = oa('W9', '2023-03-01', '10.48550/arXiv.2303.00009', title='Widgets revisited, preprint')
        self.route([(ARXIV_BATCH, arxiv_batch({'2303.00009': '10.1/FORBID'})), (r'api\.openalex\.org/works\?', self.page(w, WORKS[1]))])
        B = barrier(); out, _ = gw.search_openalex('widgets', 2, B)
        self.assertEqual([o['id'] for o in out], ['arxiv:2301.00001'])
        self.assertEqual(B.excluded, 1)
        self.assertEqual(len([u for u in self.urls if 'export.arxiv.org' in u]), 1, 'one arXiv batch for the page')

    def test_journal_doi_listed_in_openalex_locations(self):
        w = dict(oa('W9', '2023-03-01', '10.48550/arXiv.2303.00009', title='Widgets revisited, preprint'),
                 locations=[{'landing_page_url': 'https://arxiv.org/abs/2303.00009'}, {'landing_page_url': 'https://doi.org/10.1/forbid'}])
        self.route([(ARXIV_BATCH, arxiv_batch()), (r'api\.openalex\.org/works\?', self.page(w))])
        self.assertEqual(gw.search_openalex('widgets', 1, barrier())[0], [])
        self.assertIn('locations', [u for u in self.urls if 'api.openalex.org' in u][0])   # the field is asked of OpenAlex

    def test_no_arxiv_record_refused_and_chaining_rechecked(self):
        self.route([(ARXIV_BATCH, arxiv_batch(missing=('2301.00001',)))] + self.table())
        B = barrier(); out, _ = gw.search_openalex('widgets', 8, B)
        self.assertNotIn('arxiv:2301.00001', [o['id'] for o in out])            # strict: no arXiv record read -> refused
        self.route([(ARXIV_BATCH, arxiv_batch({'2302.00002': 'doi:10.1/forbid'}))] + self.table())
        out, _ = gw.references('arxiv:2306.00010', 50, barrier())
        self.assertNotIn('arxiv:2302.00002', [o['id'] for o in out])            # references (OpenAlex chaining) go through the same recheck


class ForbiddenListNormalised(unittest.TestCase):
    """Security review of 2026-10-31, item 3: forbidden entries with an arXiv version, a doi: or resolver prefix, or an arXiv DOI with a version
    match the candidates, which are built without version nor prefix."""
    def test_forms(self):
        B = gw.Barrier(T, forbidden_dois=['arXiv:2401.01234v2', 'doi:10.1/X', '10.48550/arXiv.2402.00002v1', 'https://doi.org/10.2/y', '2403.00003v3'])
        for cand in ('10.1/x', 'doi:10.1/X', '10.2/y', 'arxiv:2401.01234', '2401.01234', '10.48550/arxiv.2401.01234', 'arxiv:2402.00002',
                     '10.48550/arXiv.2402.00002', '2402.00002', 'arxiv:2403.00003', 'https://doi.org/10.48550/arXiv.2403.00003v1'):
            self.assertFalse(C.extra_ok(B, [cand], [V]), cand)
            self.assertFalse(B.ok(cand, V), cand)
        self.assertTrue(C.extra_ok(B, ['10.1/xy', 'arxiv:2401.01235'], [V]))
        self.assertTrue(B.ok('10.1/other', V))


class ReadArxivDoi(Base):
    def test_read_arxiv_doi_is_read_arxiv(self):
        self.route(self.table()); B = barrier()
        r = gw.read('doi:10.48550/arXiv.2301.00001v2', B)
        self.assertEqual((r.get('id'), r.get('abstract')), ('arxiv:2301.00001', 'We survey widgets.'), r)
        self.assertTrue(any('export.arxiv.org' in u and 'id_list=2301.00001v1' in u for u in self.urls))   # v1, like read arxiv:
        self.route([(r'export\.arxiv\.org', atom(FORBIDDEN_AX, '2024-01-10'))])
        for ident in ('doi:10.48550/arXiv.' + FORBIDDEN_AX, 'arxiv:' + FORBIDDEN_AX):   # forbidden as an arXiv DOI: refused on the arXiv engine too
            self.assertIn('refusal', gw.read(ident, barrier()), ident)
        B = barrier(); self.assertEqual(gw.search_arxiv('widgets', 5, B)[0], []); self.assertEqual(B.excluded, 1)


class ValidateResult(unittest.TestCase):
    def study(self, ident, c):
        return {'id': ident, 'title': 'T', 'year': '2023', 'confidence': c, 'basis': 'abstract', 'criteria': {k: 'x' for k in VR.CRITERIA}}

    def test_both_forms_accepted_and_one_work(self):
        r = {'studies': [self.study('doi:10.48550/arXiv.2301.00001', 0.9), self.study('arxiv:hep-th/9901001', 0.8)], 'saturation': 's', 'calls_used': 1}
        self.assertEqual(VR.problems(r), [])
        r['studies'].append(self.study('arxiv:2301.00001v2', 0.5))
        self.assertTrue(any('studies[2].id: duplicate' in p for p in VR.problems(r)), VR.problems(r))


if __name__ == '__main__':
    unittest.main()
