# SPDX-License-Identifier: Apache-2.0
"""arXiv (Atom API): search-arxiv, read arxiv:<id> (v1: notice and abstract of the initial deposit)."""
import xml.etree.ElementTree as ET
import re
import urllib.error, urllib.parse, urllib.request
from sources._common import fetch
from sources._common import preprint_unless_venue


NS = {'a': 'http://www.w3.org/2005/Atom', 'x': 'http://arxiv.org/schemas/atom', 'os': 'http://a9.com/-/spec/opensearch/1.1/'}


def arxiv_item(e, B, with_abstract=False):
    aid = (e.findtext('a:id', default='', namespaces=NS)).rsplit('/', 1)[-1]
    base = re.sub(r'v\d+$', '', aid)
    pub = e.findtext('a:published', default='', namespaces=NS)
    title = ' '.join((e.findtext('a:title', default='', namespaces=NS)).split())
    doi = e.findtext('x:doi', default=None, namespaces=NS)
    upd = e.findtext('a:updated', default='', namespaces=NS)
    # publication (v1) AND last version < T: the abstract served is the one of the version received (frozen rule of the non-medical gateway)
    if not B.ok(doi, pub, upd or pub, title=title): return None
    it = {'id': f'arxiv:{base}', 'arxiv': base, 'doi': doi, 'title': title, 'year': pub[:4], 'journal': 'arXiv',
          'first_author': e.findtext('a:author/a:name', default='', namespaces=NS), 'date_published': pub[:10],
          'date_version': (e.findtext('a:updated', default='', namespaces=NS))[:10]}
    if with_abstract: it['abstract'] = ' '.join((e.findtext('a:summary', default='', namespaces=NS)).split())[:6000]
    return it


def search_arxiv(q, n, B):
    """arXiv search (Atom API) bounded on the provider side by submission date; local recheck on "published" (v1) < T."""
    sq = f'({q}) AND submittedDate:[{B.start:%Y%m%d}0000 TO {B.eve:%Y%m%d}2359]'
    root = ET.fromstring(fetch('https://export.arxiv.org/api/query?' + urllib.parse.urlencode({'search_query': sq, 'max_results': n, 'sortBy': 'relevance'})))
    out = [x for x in (arxiv_item(e, B) for e in root.findall('a:entry', NS)) if x]
    return out, root.findtext('os:totalResults', default=None, namespaces=NS)


def read_arxiv(ident, B):
    """Explicit reading of v1: notice and abstract dated from the initial deposit (< T required)."""
    aid = re.sub(r'v\d+$', '', ident[6:].strip()) + 'v1'
    root = ET.fromstring(fetch('https://export.arxiv.org/api/query?' + urllib.parse.urlencode({'id_list': aid})))
    for e in root.findall('a:entry', NS):
        it = arxiv_item(e, B, with_abstract=True)
        return it or {'refusal': 'after T or forbidden'}
    return {'refusal': 'not found'}


def _arxiv_ok(ident, B):
    """An arXiv identifier goes to OpenAlex chaining only when its "published" (v1) is before T."""
    return 'refusal' not in read_arxiv(ident, B)


SOURCE = {
    'name': 'arxiv', 'order': 30,
    'engines': {'arxiv': search_arxiv},
    'ids': [{'prefix': 'arxiv', 'form': r'\d{4}\.\d{4,5}(v\d+)?|[a-z-]+(\.[A-Z]{2})?/\d{7}(v\d+)?', 'export': preprint_unless_venue, 'export_rank': 100}],
    'read': read_arxiv,
    'plugins': ('cs-ai', 'finance'), 'access': 'api',
    'hosts': {'export.arxiv.org': {'interval': 3.0}},
    'terms': 'arXiv API terms of use (one request every 3 s); metadata CC0',
    'barrier': 'provider side: submittedDate in [start, eve of T]; local: published (v1) AND last updated < T; read serves v1 only',
}
