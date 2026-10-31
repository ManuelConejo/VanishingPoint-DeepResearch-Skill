# SPDX-License-Identifier: Apache-2.0
"""arXiv (Atom API): search-arxiv, read arxiv:<id> (v1: notice and abstract of the initial deposit)."""
import xml.etree.ElementTree as ET
import re
import urllib.error, urllib.parse, urllib.request
from sources._common import fetch
from sources._common import ARXIV_DOI, ARXIV_FORM, CFG, extra_ok, preprint_unless_venue, title_sim, tokens


NS = {'a': 'http://www.w3.org/2005/Atom', 'x': 'http://arxiv.org/schemas/atom', 'os': 'http://a9.com/-/spec/opensearch/1.1/'}


def arxiv_item(e, B, with_abstract=False):
    aid = (e.findtext('a:id', default='', namespaces=NS)).rsplit('/', 1)[-1]
    base = re.sub(r'v\d+$', '', aid)
    pub = e.findtext('a:published', default='', namespaces=NS)
    title = ' '.join((e.findtext('a:title', default='', namespaces=NS)).split())
    doi = e.findtext('x:doi', default=None, namespaces=NS)
    upd = e.findtext('a:updated', default='', namespaces=NS)
    # publication (v1) AND last version < T: the abstract served is the one of the version received (frozen rule of the non-medical gateway)
    # forbidden as its venue DOI, its arXiv DOI (10.48550/arXiv.<id>), arxiv:<id> or the bare id
    if not extra_ok(B, [doi, ARXIV_DOI + base, 'arxiv:' + base, base], [pub, upd or pub], [title]): return None
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


def arxiv_recheck(items, B):
    """arxiv:<id> items served by another lane (OpenAlex): kept only when their arXiv record (one id_list request per
    arxiv_recheck.ids_per_request ids, config.json) names no forbidden venue DOI (<arxiv:doi>, the journal version) and no forbidden title.
    Strict: an item whose record arXiv does not return (or a failed request) is refused, as a DOI without Crossref deposit is."""
    per = max(1, int(CFG['arxiv_recheck']['ids_per_request']))
    ids = list(dict.fromkeys(x['arxiv'] for x in items))
    ok = set()
    for i in range(0, len(ids), per):
        lot = ids[i:i + per]
        try: root = ET.fromstring(fetch('https://export.arxiv.org/api/query?' + urllib.parse.urlencode({'id_list': ','.join(lot), 'max_results': len(lot)})))
        except Exception: continue                                          # noqa: BLE001  (no record read: the lot is refused)
        for e in root.findall('a:entry', NS):
            base = re.sub(r'v\d+$', '', (e.findtext('a:id', default='', namespaces=NS)).rsplit('/abs/', 1)[-1])
            doi = e.findtext('x:doi', default=None, namespaces=NS)
            title = ' '.join((e.findtext('a:title', default='', namespaces=NS)).split())
            if base not in lot: continue
            if (doi and B.is_forbidden(doi)) or (title and any(title_sim(tokens(title), f) >= CFG['review_title_threshold'] for f in B.titles)): continue
            ok.add(base)
    kept = [x for x in items if x['arxiv'] in ok]
    B.excluded += len(items) - len(kept)
    return kept


SOURCE = {
    'name': 'arxiv', 'order': 30,
    'engines': {'arxiv': search_arxiv},
    'ids': [{'prefix': 'arxiv', 'form': ARXIV_FORM, 'export': preprint_unless_venue, 'export_rank': 100}],
    'read': read_arxiv,
    'plugins': ('cs-ai', 'finance'), 'access': 'api',
    'hosts': {'export.arxiv.org': {'interval': 3.0}},
    'terms': 'arXiv API terms of use (one request every 3 s); metadata CC0',
    'barrier': 'provider side: submittedDate in [start, eve of T]; local: published (v1) AND last updated < T; read serves v1 only',
}
