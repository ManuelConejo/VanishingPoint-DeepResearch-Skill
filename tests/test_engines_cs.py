#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""CS engines added on 2026-10-28 (v0.4.6, plugins/cs-ai.md): hf-models, hf-datasets, standards (RFC, PEP, W3C), proceedings (ACL Anthology,
PMLR, CVF) and the command `related` (OpenAlex related works). Everything offline (fetch replaced). Per engine: only the record dated before T
is served (after T, day T, partial date at the year of T, forbidden id or title, no date: refused); the HF card is read at the last commit
before T, never today's; an obsoleting RFC published on/after T is not shown; every related work is rechecked; no key nor e-mail in a URL.
Run: python3 -I tests/test_engines_cs.py
"""
import datetime as dt, gzip, json, os, pathlib, re, sys, tempfile, unittest, urllib.error, urllib.parse
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import gateway as gw   # noqa: E702

T = dt.date(2024, 3, 15); V, F = '2024-03-14', '2024-03-16'
FORBID_T = 'Forbidden landmark survey of retrieval augmented generation'


def barrier(): return gw.Barrier(T, forbidden_dois=['10.1/forbid', 'org/forbidden-model', '10.48550/arxiv.2401.99999'], forbidden_titles=[FORBID_T])


def http404(url): return urllib.error.HTTPError(url, 404, 'not found', {}, None)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); gw.STATE = pathlib.Path(self.tmp.name); self.fetch0 = gw.fetch; self.urls = []
        self.contact = os.environ.get('VP_CONTACT'); os.environ['VP_CONTACT'] = 'someone@example.org'   # must never reach a URL

    def tearDown(self):
        gw.fetch = self.fetch0; self.tmp.cleanup()
        if self.contact is None: os.environ.pop('VP_CONTACT', None)
        else: os.environ['VP_CONTACT'] = self.contact

    def route(self, table):
        """fetch replaced: the first (pattern, answer) whose pattern is found in the URL answers (callable(url) or bytes/str/JSON)."""
        def fetch(url, headers=None):
            self.urls.append(urllib.parse.unquote_plus(url))
            for pat, ans in table:
                if re.search(pat, url):
                    a = ans(url) if callable(ans) else ans
                    return a if isinstance(a, bytes) else (a if isinstance(a, str) else json.dumps(a)).encode()
            raise http404(url)
        gw.fetch = fetch

    def clean(self):
        self.assertTrue(self.urls)
        for u in self.urls:                                               # Crossref alone carries the VP_CONTACT polite-pool mailto (existing rule)
            if 'api.crossref.org' not in u: self.assertFalse('@' in u or re.search(r'api_key|apikey|token|key=|mailto', u, re.I), u)


def crossref(dates):
    """Crossref batch filter=doi:a,doi:b -> items with (created, issued) from `dates`; an unknown DOI is absent."""
    def ans(url):
        ds = re.findall(r'doi:([^,&]+)', urllib.parse.unquote(url))
        return {'message': {'items': [{'DOI': d, 'title': ['t'], 'created': {'date-time': dates[d][0] + 'T00:00:00Z'}, 'issued': {'date-parts': [[int(x) for x in dates[d][1].split('-')]]}}
                                      for d in ds if d in dates]}}
    return ans


# ---------------------------------------------------------------- Hugging Face Hub

def repo(i, created=V + 'T10:00:00.000Z', modified=V + 'T10:00:00.000Z', **kw):
    r = {'id': i, 'author': i.split('/')[0], 'downloads': 5, 'likes': 2, 'tags': ['license:mit', 'arxiv:2401.00001'], 'pipeline_tag': 'fill-mask',
         'library_name': 'transformers', 'cardData': {'license': 'mit'}, 'lastModified': modified}
    if created: r['createdAt'] = created
    r.update(kw); return r


HF_REPOS = [repo('org/old'), repo('org/late', created=F + 'T01:00:00.000Z'), repo('org/dayT', created=T.isoformat() + 'T00:00:01.000Z'),
            repo('org/partial', created='2024'), repo('org/forbidden-model'), repo('org/forbidden-landmark-survey-of-retrieval-augmented-generation'),
            repo('org/linked', tags=['arxiv:2401.99999']), repo('org/nodate', created=None), repo('org/modified', modified=F + 'T00:00:00.000Z'),
            repo('org/legacy', created='2022-03-02T23:29:04.000Z'), repo('org/legacy-new', created='2022-03-02T23:29:04.000Z')]
COMMITS = {'org/old': [{'id': 'c3', 'date': F + 'T08:00:00.000Z'}, {'id': 'c2', 'date': '2024-01-05T08:00:00.000Z'}, {'id': 'c1', 'date': '2023-12-01T08:00:00.000Z'}],
           'org/legacy': [{'id': 'L2', 'date': '2021-06-01T00:00:00.000Z'}, {'id': 'L1', 'date': '2020-12-01T00:00:00.000Z'}],
           'org/legacy-new': [{'id': 'N1', 'date': F + 'T00:00:00.000Z'}], 'org/late': [{'id': 'x1', 'date': F + 'T02:00:00.000Z'}]}
MODEL_INDEX = [{'name': 'org/old', 'results': [{'task': {'type': 'question-answering'}, 'dataset': {'name': 'squad_v2', 'split': 'validation'},
                                                'metrics': [{'name': 'Exact Match', 'value': 79.9, 'verified': False}]}]}]


def hf_table(T_=T):
    def commits(url):
        rid = re.search(r'/api/(?:models|datasets)/(.+?)/commits/main', url).group(1); p = int(re.search(r'[?&]p=(\d+)', url).group(1))
        return COMMITS.get(rid, [])[p * 100:(p + 1) * 100]
    def info(url):
        rid = re.search(r'/api/(?:models|datasets)/(.+)$', url).group(1)
        r = next((x for x in HF_REPOS if x['id'] == rid), None)
        if not r: raise http404(url)
        return r
    def revision(url):
        sha = url.rsplit('/', 1)[-1]
        return {'sha': sha, 'cardData': {'license': 'mit' if sha != 'c2' else 'apache-2.0', 'model-index': MODEL_INDEX, 'datasets': ['squad_v2']}, 'pipeline_tag': 'question-answering'}
    return [(r'/api/(models|datasets)\?', lambda u: HF_REPOS), (r'/commits/main\?', commits), (r'/revision/', revision),
            (r'/raw/(\w+)/README\.md', lambda u: '---\nlicense: x\n---\n# Card at ' + re.search(r'/raw/(\w+)/', u).group(1)), (r'/api/(models|datasets)/[^?]+$', info)]


class HfHub(Base):
    def test_search_barrier(self):
        self.route(hf_table()); B = barrier()
        out, tot = gw.search_hf_models('org', 20, B)
        self.assertEqual([o['id'] for o in out], ['hfmodel:org/old', 'hfmodel:org/modified', 'hfmodel:org/legacy', 'hfmodel:org/legacy-new'])
        self.assertEqual((out[0]['licence'], out[0]['task'], out[0]['as_of'], out[0]['downloads']), ('mit', 'fill-mask', 'now', 5))
        self.assertNotIn('licence', out[1]); self.assertIn('masked', out[1]['metadata'])               # lastModified >= T: licence, task, tags masked
        self.assertEqual(out[2]['date'], '2022-03-02'); self.assertNotIn('date_note', out[2])            # migration day before T: createdAt suffices
        self.assertEqual(B.excluded, 7)                                                                  # late, day T, partial, forbidden id/title/arXiv, no date
        self.assertFalse(any('/commits/' in u for u in self.urls))
        self.assertIn('no provider-side date filter', tot)
        self.assertFalse(any('/raw/' in u for u in self.urls))
        self.clean()

    def test_legacy_before_migration_day(self):
        self.route(hf_table()); B = gw.Barrier('2022-01-01')                                             # T before the migration day: a commit < T dates the repo
        out, tot = gw.search_hf_models('org', 20, B)
        self.assertEqual([o['id'] for o in out], ['hfmodel:org/legacy']); self.assertEqual(out[0]['date'], '2021-06-01'); self.assertIn('migration', out[0]['date_note'])
        self.assertIn('2 lookups', tot)                                                                  # legacy-new: its only commit is after T
        self.urls.clear(); out, tot = gw.search_hf_models('org', 1, gw.Barrier('2022-01-01'))
        self.assertEqual(len(out), 1); self.assertEqual(sum('/commits/' in u for u in self.urls), 1)   # n=1: at most one commit lookup
        r = gw.read('hfmodel:org/legacy', gw.Barrier('2022-01-01')); self.assertEqual((r['revision'], r['date'], r['date_created']), ('L2', '2021-06-01', None))   # no date on/after T is served
        self.assertIn('refusal', gw.read('hfmodel:org/legacy-new', gw.Barrier('2022-01-01')))

    def test_read_card_at_revision_before_T(self):
        self.route(hf_table()); B = barrier()
        r = gw.read('hfmodel:org/old', B)
        self.assertEqual((r['revision'], r['revision_date'], r['later_commits_masked']), ('c2', '2024-01-05', 1))
        self.assertEqual(r['licence'], 'apache-2.0'); self.assertEqual(r['abstract'], '# Card at c2')       # card text and metadata at c2, front matter dropped
        self.assertEqual(r['eval_results'][0]['metric'], 'Exact Match'); self.assertEqual(r['eval_results'][0]['value'], 79.9)
        self.assertEqual(r['as_of'], 'now')
        self.assertFalse(any('/raw/c3/' in u or '/revision/c3' in u or '/raw/main/' in u for u in self.urls))   # today's card is never read
        r = gw.read('hfmodel:org/legacy', B); self.assertEqual((r['revision'], r['date']), ('L2', '2022-03-02'))
        for i in ('org/late', 'org/legacy-new', 'org/forbidden-model', 'org/linked'): self.assertIn('refusal', gw.read('hfmodel:' + i, B), i)
        self.assertIn('no commit dated before T', gw.read('hfmodel:org/legacy-new', B)['refusal'])
        self.assertIn('refusal', gw.read('hfmodel:org/unknown', B)); self.assertIn('refusal', gw.read('hfmodel:../x', B))
        r = gw.read('hfdataset:org/old', B); self.assertEqual(r['type'], 'dataset')
        self.assertTrue(any('huggingface.co/datasets/org/old/raw/c2/README.md' in u for u in self.urls))
        self.clean()

    def test_no_commit_before_T_refuses_card(self):
        tab = hf_table(); COMMITS['org/modified'] = [{'id': 'm1', 'date': F + 'T00:00:00.000Z'}]
        self.addCleanup(COMMITS.pop, 'org/modified')
        self.route(tab); B = barrier()
        self.assertIn('no commit dated before T', gw.read('hfmodel:org/modified', B)['refusal'])
        self.assertFalse(any('/revision/' in u or '/raw/' in u for u in self.urls))


# ---------------------------------------------------------------- Standards

def rfc_entry(n, title, date, obs_by=(), upd_by=(), doi=None, abstract='About the protocol.'):
    y, m = (date.split(' ') + [''])[:2] if date else ('', '')
    d = f'<date>{f"<month>{m}</month>" if m else ""}{f"<year>{y}</year>" if y else ""}</date>' if date else ''
    ids = lambda tag, xs: f'<{tag}>' + ''.join(f'<doc-id>RFC{x}</doc-id>' for x in xs) + f'</{tag}>' if xs else ''
    return (f'<rfc-entry><doc-id>RFC{n}</doc-id><title>{title}</title><author><name>A. Author</name></author>{d}<abstract><p>{abstract}</p></abstract>'
            f'{ids("obsoleted-by", obs_by)}{ids("updated-by", upd_by)}<publication-status>PROPOSED STANDARD</publication-status><current-status>HISTORIC</current-status>'
            f'<stream>IETF</stream><doi>{doi or f"10.17487/RFC{n}"}</doi></rfc-entry>')


RFC_XML = ('<?xml version="1.0"?><rfc-index xmlns="https://www.rfc-editor.org/rfc-index"><bcp-entry><doc-id>BCP1</doc-id></bcp-entry>'
           + rfc_entry(100, 'Widget transport protocol', '2020 January', obs_by=[200], upd_by=[150, 300])
           + rfc_entry(150, 'Widget transport protocol update', '2023 June') + rfc_entry(200, 'Widget transport protocol version 2', '2024 March')
           + rfc_entry(300, 'Widget transport protocol later', '2025 May') + rfc_entry(400, 'Widget transport protocol partial', '2024')
           + rfc_entry(500, 'Widget transport protocol forbidden doi', '2019 May', doi='10.1/forbid') + rfc_entry(600, FORBID_T + ' widget transport protocol', '2019 May')
           + rfc_entry(700, 'Widget transport protocol undated', '') + '</rfc-index>')
PEPS = {'1': {'number': 1, 'title': 'Widget hints', 'created': '05-Jul-2001', 'type': 'Standards Track', 'status': 'Final', 'superseded_by': '2, 3', 'author_names': ['G. V.'], 'url': 'u1'},
        '2': {'number': 2, 'title': 'Widget hints again', 'created': '16-Mar-2024', 'status': 'Draft', 'superseded_by': None, 'author_names': [], 'url': 'u2'},
        '3': {'number': 3, 'title': 'Widget hints bis', 'created': '01-Jan-2020', 'status': 'Final', 'superseded_by': None, 'author_names': [], 'url': 'u3'},
        '4': {'number': 4, 'title': 'Widget hints undated', 'created': 'someday', 'status': 'Final', 'superseded_by': None, 'author_names': [], 'url': 'u4'}}
W3C_LIST = {'pages': 1, '_links': {'specifications': [{'href': 'https://api.w3.org/specifications/widget-api', 'title': 'Widget API'},
                                                       {'href': 'https://api.w3.org/specifications/widget-new', 'title': 'Widget API Next'}]}}
W3C_VERS = {'widget-api': [{'date': '2019-01-10', 'status': 'Working Draft', 'uri': 'https://www.w3.org/TR/2019/WD-widget-api-20190110/', 'title': 'Widget API'},
                           {'date': '2024-03-20', 'status': 'Recommendation', 'uri': 'https://www.w3.org/TR/2024/REC-widget-api-20240320/', 'title': 'Widget API'}],
            'widget-new': [{'date': F, 'status': 'Working Draft', 'uri': 'https://www.w3.org/TR/2024/WD-widget-new/', 'title': 'Widget API Next'}]}


def std_table():
    def gh(url):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        if q['path'][0] != 'pep-0001.txt': return []                       # only the old root path has history before the move
        return [{'sha': 'abc123', 'commit': {'author': {'date': '2020-05-01T00:00:00Z'}, 'committer': {'date': '2020-05-02T00:00:00Z'}}}]
    return [(r'rfc-index\.xml', RFC_XML), (r'rfc-editor\.org/rfc/rfc\d+\.txt', 'RFC TEXT'), (r'peps\.json', PEPS),
            (r'api\.github\.com/repos/python/peps/commits', gh),
            (r'raw\.githubusercontent\.com/python/peps/abc123/pep-0001\.txt', 'PEP: 1\nTitle: Widget hints\nStatus: Accepted\nPython-Version: 3.5\n\nBody text'),
            (r'api\.w3\.org/specifications\?', W3C_LIST),
            (r'api\.w3\.org/specifications/([\w-]+)/versions', lambda u: {'_embedded': {'version-history': W3C_VERS[re.search(r'specifications/([\w-]+)/', u).group(1)]}}),
            (r'w3\.org/TR/2019/', '<html><section id="abstract"><h2>Abstract</h2><p>The widget API &amp; more.</p></section></html>')]


class Standards(Base):
    def test_search_barrier(self):
        self.route(std_table()); B = barrier()
        out, tot = gw.search_standards('widget transport protocol', 20, B)
        self.assertEqual(sorted(o['id'] for o in out), ['rfc:100', 'rfc:150'])
        r100 = next(o for o in out if o['id'] == 'rfc:100')
        self.assertEqual(r100['obsoleted_by'], []); self.assertEqual(r100['updated_by'], ['RFC150'])   # RFC 200 (month of T) and 300 (after T) hidden
        self.assertEqual(r100['status_at_publication'], 'PROPOSED STANDARD'); self.assertNotIn('HISTORIC', json.dumps(out))   # current status never served
        self.assertEqual(B.excluded, 6)                                                                  # 200 month of T, 300 after, 400 partial, 500 doi, 600 title, 700 undated
        self.assertIn('RFC 8', tot)

    def test_obsoleted_by_shown_when_before_T(self):
        self.route(std_table()); B = gw.Barrier('2024-04-01')
        self.assertEqual(gw.read('rfc:100', B)['obsoleted_by'], ['RFC200'])

    def test_read_rfc(self):
        self.route(std_table()); B = barrier()
        r = gw.read('rfc:100', B); self.assertEqual((r['text'], r['date'], r['abstract']), ('RFC TEXT', '2020 January', 'About the protocol.'))
        for i in ('200', '300', '400', '500', '600', '700'): self.assertIn('refusal', gw.read('rfc:' + i, B), i)
        self.assertIn('refusal', gw.read('rfc:x', B)); self.assertIn('not found', gw.read('rfc:999', B)['refusal'])
        self.clean()

    def test_pep(self):
        self.route(std_table()); B = barrier()
        out, _ = gw.search_standards('widget hints', 20, B)
        self.assertEqual([o['id'] for o in out], ['pep:3', 'pep:1'])                                     # most recent first; 2 after T, 4 undated
        p1 = out[1]; self.assertIsNone(p1['status']); self.assertEqual(p1['superseded_by'], ['3'])     # PEP 2 created after T: not shown
        r = gw.read('pep:1', B)
        self.assertEqual((r['status'], r['python_version'], r['revision']), ('Accepted', '3.5', 'abc123'))   # header at the commit before T, not 'Final'
        self.assertTrue(all('until=2024-03-14T23:59:59Z' in u for u in self.urls if 'api.github.com' in u))
        self.assertIn('refusal', gw.read('pep:2', B)); self.assertIn('refusal', gw.read('pep:4', B))
        self.assertIn('no version of the PEP text', gw.read('pep:3', B)['refusal'])                     # no commit before T found: refused, never today's text
        self.clean()

    def test_w3c(self):
        self.route(std_table()); B = barrier()
        out, _ = gw.search_standards('widget api', 20, B)
        self.assertEqual([o['id'] for o in out], ['w3c:widget-api'])
        w = out[0]; self.assertEqual((w['status'], w['date_version'], w['later_versions_masked']), ('Working Draft', '2019-01-10', 1))
        self.assertNotIn('Recommendation', json.dumps(out))
        r = gw.read('w3c:widget-api', B); self.assertEqual(r['abstract'], 'Abstract The widget API & more.')
        self.assertTrue(r['url'].startswith('https://www.w3.org/TR/2019/'))
        self.assertIn('refusal', gw.read('w3c:widget-new', B)); self.assertEqual(B.excluded, 2)


# ---------------------------------------------------------------- Proceedings

ACL_BIB = '\n'.join(f'@inproceedings{{k{i},\n    title = "{t}",\n    author = "Last{i}, First and Other, A.",\n    booktitle = "Proceedings of ACL",\n'
                    + (f'    month = {m},\n' if m else '') + (f'    year = "{y}",\n' if y else '') + f'    url = "https://aclanthology.org/{aid}/",\n'
                    + (f'    doi = "{doi}",\n' if doi else '') + '}\n'
                    for i, (aid, t, y, m, doi) in enumerate([
                        ('2023.acl-long.1', 'Widget parsing with {T}ransformers', '2023', 'jul', '10.18653/v1/2023.acl-long.1'),
                        ('2024.eacl-long.2', 'Widget parsing in March', '2024', 'mar', None), ('2024.naacl-long.3', 'Widget parsing later', '2024', 'jun', None),
                        ('2024.x-1.4', 'Widget parsing year only', '2024', None, None), ('2023.y-1.5', 'Widget parsing old year only', '2023', None, None),
                        ('2023.z-1.6', 'Widget parsing forbidden doi', '2023', 'may', '10.1/forbid'), ('2023.z-1.7', FORBID_T + ' widget parsing', '2023', 'may', None),
                        ('2023.z-1.8', 'Widget parsing undated', None, None, None), ('2023.z-1.9', 'Widget parsing doi not deposited', '2023', 'jun', '10.18653/v1/late'),
                        ('2024.eacl-short.10', 'Widget parsing ranges', '2024', 'feb # "--" # mar', None)]))
PMLR_HOME = ('<ul class="proceedings-list"><li><a href="v300"><b>Volume 300</b></a> Proceedings of ICML 2024</li>'
             '<li><a href="v200"><b>Volume 200</b></a> Proceedings of ICML 2023</li><li><a href="v199"><b>Volume 199</b></a> GRaM Workshop at ICML 2023</li></ul>')


def feed(v, date, papers):
    items = ''.join(f'<item><title>{t}</title><description>{a}</description><link>https://proceedings.mlr.press/{v}/{k}.html</link></item>' for k, t, a in papers)
    return (f'<?xml version="1.0"?><rss version="2.0"><channel><title>PMLR</title><description>Proceedings of the Conference on Widgets\n  Held in X\n\n'
            f'Published as Volume {v[1:]} by the Proceedings of Machine Learning Research on {date}.\n</description>{items}</channel></rss>')


CVF_MENU = ('<dd>CVPR 2024, Seattle [<a href="CVPR2024">Main Conference</a>] <span>(Published: June 10, 2024)</span></dd>'
            '<dd>CVPR 2023, Vancouver [<a href="CVPR2023">Main Conference</a>] <span style="x">(Published: June 1, 2023)</span></dd>'
            '<dd>WACV 2023 [<a href="WACV2023">Main Conference</a>]  [<a href="/WACV2023_workshops/menu">Workshops</a>]</dd>')
CVF_LIST = ('<dt class="ptitle"><br><a href="/content/CVPR2023/html/A_Widget_Parsing_Vision_CVPR_2023_paper.html">Widget parsing vision</a></dt>'
            '<dt class="ptitle"><br><a href="/content/CVPR2023/html/B_Forbidden_CVPR_2023_paper.html">' + FORBID_T + ' widget parsing</a></dt>')


def proc_table():
    return [(r'aclanthology\.org/anthology\.bib\.gz', lambda u: gzip.compress(ACL_BIB.encode())),
            (r'aclanthology\.org/2023\.acl-long\.1\.bib', ACL_BIB.split('\n@')[0]), (r'aclanthology\.org/2024\.eacl-long\.2\.bib', '@' + ACL_BIB.split('\n@')[1]),
            (r'aclanthology\.org/2023\.acl-long\.1/$', '<div class="card-body acl-abstract"><h5>Abstract</h5><span>We parse <i>widgets</i>.</span></div>'),
            (r'api\.crossref\.org/works\?', crossref({'10.18653/v1/2023.acl-long.1': ('2023-07-01', '2023-07')})),
            (r'proceedings\.mlr\.press/$', PMLR_HOME),
            (r'v300/assets/rss/feed\.xml', feed('v300', '20 March 2024', [('a24', 'Widget parsing at ICML 2024', 'abs')])),
            (r'v200/assets/rss/feed\.xml', feed('v200', '03 July 2023', [('b23a', 'Widget parsing at ICML 2023', 'We parse widgets.'), ('b23b', 'Unrelated', 'widget parsing in the abstract')])),
            (r'proceedings\.mlr\.press/v200/b23a\.html', '<meta name="citation_title" content="Widget parsing at ICML 2023"><meta name="citation_author" content="First, A.">'
                                                       '<meta name="citation_author" content="Second, B."><meta name="citation_publication_date" content="2023/07/03"><div id="abstract" class="abstract">We parse.</div>'),
            (r'proceedings\.mlr\.press/v300/a24\.html', '<meta name="citation_title" content="Widget parsing at ICML 2024"><meta name="citation_publication_date" content="2024/03/20">'),
            (r'openaccess\.thecvf\.com/menu', CVF_MENU), (r'openaccess\.thecvf\.com/CVPR2023\?day=all', CVF_LIST),
            (r'openaccess\.thecvf\.com/WACV2023\?day=all', 'no papers here'), (r'openaccess\.thecvf\.com/WACV2023$', '<a href="WACV2023.py?day=2023-01-04">Day 1</a>'),
            (r'openaccess\.thecvf\.com/WACV2023\?day=2023-01-04', '<dt class="ptitle"><br><a href="content/WACV2023/html/C_Widget_Parsing_Day_WACV_2023_paper.html">Widget parsing day</a></dt>'),
            (r'content/CVPR2023/html/A_Widget_Parsing_Vision_CVPR_2023_paper\.html', '<meta name="citation_title" content="Widget parsing vision"><meta name="citation_author" content="Ax, B.">'
                                                                                   '<div id="abstract">Vision of <b>widgets</b>.</div>')]


class Proceedings(Base):
    def test_search_barrier(self):
        self.route(proc_table()); B = barrier()
        out, tot = gw.search_proceedings('widget parsing', 20, B)
        ids = [o['id'] for o in out]
        self.assertEqual(set(ids), {'acl:2023.acl-long.1', 'acl:2023.y-1.5', 'pmlr:v200/b23a', 'pmlr:v200/b23b', 'cvf:content/CVPR2023/html/A_Widget_Parsing_Vision_CVPR_2023_paper',
                                    'cvf:content/WACV2023/html/C_Widget_Parsing_Day_WACV_2023_paper'})
        self.assertIn('v200 ICML 2023', tot); self.assertNotIn('v300', tot); self.assertNotIn('v199', tot)   # volume of T's year published after T, workshop: not searched
        self.assertIn('CVPR2023', tot); self.assertNotIn('CVPR2024', tot)
        acl = next(o for o in out if o['id'] == 'acl:2023.acl-long.1')
        self.assertEqual((acl['title'], acl['date'], acl['first_author'], acl['doi']), ('Widget parsing with Transformers', '2023 Jul', 'Last0', '10.18653/v1/2023.acl-long.1'))
        self.assertEqual(next(o for o in out if o['id'] == 'pmlr:v200/b23a')['date'], '2023-07-03')
        self.assertEqual(next(o for o in out if o['id'].startswith('cvf:content/CVPR'))['date'], '2023-06-01')
        self.assertEqual(next(o for o in out if o['id'].startswith('cvf:content/WACV'))['date'], '2023')            # undated conference: year < year of T
        # refused: month of T, after, year of T only, forbidden DOI, forbidden title (ACL and CVF), undated, DOI not deposited, month range ending in T's month
        self.assertEqual(B.excluded, 9)
        self.assertNotIn('2024', json.dumps([o['date'] for o in out]))
        self.clean()

    def test_read(self):
        self.route(proc_table()); B = barrier()
        r = gw.read('acl:2023.acl-long.1', B); self.assertEqual((r['abstract'], r['full_text']), ('We parse widgets .', 'PDF only (not parsed)'))
        self.assertIn('refusal', gw.read('acl:2024.eacl-long.2', B)); self.assertIn('refusal', gw.read('acl:../x', B))
        r = gw.read('pmlr:v200/b23a', B); self.assertEqual((r['date'], r['first_author'], r['abstract']), ('2023-07-03', 'First, A.', 'We parse.'))
        self.assertIn('refusal', gw.read('pmlr:v300/a24', B))
        r = gw.read('cvf:content/CVPR2023/html/A_Widget_Parsing_Vision_CVPR_2023_paper', B)
        self.assertEqual((r['date'], r['abstract'], r['first_author']), ('2023-06-01', 'Vision of widgets .', 'Ax, B.'))
        self.assertIn('refusal', gw.read('cvf:content/../etc_paper', B))
        self.clean()


# ---------------------------------------------------------------- related works (OpenAlex)

def oa(i, date, doi=None):
    return {'id': 'https://openalex.org/' + i, 'doi': 'https://doi.org/' + doi if doi else None, 'title': 'Work ' + i, 'publication_date': date, 'publication_year': int(date[:4]), 'type': 'article'}


class Related(Base):
    def table(self, seed_date=V):
        works = {'W1': oa('W1', '2023-01-01', '10.1/w1'), 'W2': oa('W2', F, '10.1/w2'), 'W3': oa('W3', '2023-02-01'), 'W4': oa('W4', '2023-03-01', '10.1/w4'),
                 'W5': oa('W5', '2023-04-01', '10.1/forbid')}
        seed = dict(oa('W0', seed_date, '10.1/seed'), related_works=['https://openalex.org/W' + str(i) for i in range(1, 6)])
        def batch(url):
            ids = re.search(r'openalex_id:([\w|]+)', urllib.parse.unquote(url)).group(1).split('|')
            return {'results': [works[i] for i in ids if i in works]}
        return [(r'api\.openalex\.org/works/doi:10\.1/seed', seed), (r'api\.openalex\.org/works\?', batch),
                (r'api\.crossref\.org/works\?', crossref({'10.1/w1': ('2023-01-02', '2023-01-01'), '10.1/w4': (F, '2023-03-01')}))]

    def test_related_rechecked(self):
        self.route(self.table()); B = barrier()
        out, tot = gw.related('doi:10.1/seed', 20, B)
        self.assertEqual([o['id'] for o in out], ['doi:10.1/w1'])          # W2 after T, W3 no DOI, W4 deposited after T, W5 forbidden
        self.assertIn('5 related works', tot); self.assertEqual(B.excluded, 5)   # W4 counted twice (cr_item refusal, then crossref_deposit), existing rule
        g = gw.Gateway([P.parent / 'plugins' / 'cs-ai.md'], T=T, run='t-rel', state=pathlib.Path(self.tmp.name) / 's')
        self.assertIn('related', g.sources()['commands'])
        self.assertEqual([x['id'] for x in g.related('doi:10.1/seed')['results']], ['doi:10.1/w1'])
        self.clean()

    def test_related_refusals(self):
        self.route(self.table(seed_date=F)); B = barrier()
        self.assertEqual(gw.related('doi:10.1/seed', 20, B), ([], 'document after T or forbidden'))
        for i in ('rfc:100', 'hfmodel:org/old', 'acl:2023.acl-long.1', 'nct:NCT01234567'): self.assertIn('served only', gw.related(i, 20, B)[1], i)
        for f in (gw.citing, gw.references): self.assertIn('not served', f('pep:1', 20, B)[1])


# ---------------------------------------------------------------- plugin declaration and id kinds

class Declared(unittest.TestCase):
    def test_cs_ai_declares_and_ids(self):
        with tempfile.TemporaryDirectory() as d:
            s = gw.Gateway([P.parent / 'plugins' / 'cs-ai.md'], T=T, run='t-d', state=d).sources()
        self.assertTrue({'hf-models', 'hf-datasets', 'standards', 'proceedings'} <= set(s['engines']))
        for e in ('hf-models', 'hf-datasets', 'standards', 'proceedings'): self.assertNotIn(e, s['not_wired'])
        import validate_card as vc, validate_result as vr, verifier as vf, export_data as ed
        for k, v in (('hfmodel', 'google-bert/bert-base-uncased'), ('hfdataset', 'rajpurkar/squad'), ('rfc', '8446'), ('pep', '484'), ('w3c', 'webauthn-2'),
                     ('acl', '2024.acl-long.1'), ('pmlr', 'v202/aamand23a'), ('cvf', 'content/CVPR2024/html/X_CVPR_2024_paper')):
            self.assertIn(k, vc.IDS); self.assertTrue(vr.ID.match(f'{k}:{v}'), k); self.assertEqual(vf.ident_of({k: v}), f'{k}:{v}')
        self.assertEqual(ed.kind(['rfc:8446'], None, None, None), 'standard'); self.assertEqual(ed.kind(['hfdataset:a/b'], None, None, None), 'dataset')
        self.assertEqual(ed.kind(['hfmodel:a/b'], None, None, None), 'software'); self.assertEqual(ed.kind(['acl:2024.acl-long.1', 'doi:10.18653/x'], None, None, 'ACL'), 'paper')
        for h in ('huggingface.co', 'aclanthology.org', 'openaccess.thecvf.com'): self.assertIn(429, gw.STOP[h]); self.assertIn(404, gw.STOP[h])


if __name__ == '__main__':
    unittest.main()
