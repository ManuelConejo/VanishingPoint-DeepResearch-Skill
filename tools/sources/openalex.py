# SPDX-License-Identifier: Apache-2.0
"""OpenAlex: search-openalex (Crossref fallback when OpenAlex fails), related works and reference lists for the DOI chaining.
Optional OPENALEX_KEY (api_key=, own budget instead of the per-IP one)."""
import urllib.error, urllib.parse, urllib.request
from sources._common import jget, live_key
from sources.crossref import crossref_deposit, search_crossref
import code_sources as sc
from sources._common import STATE


def oa_item(w, B):
    doi = (w.get('doi') or '').replace('https://doi.org/', '') or None
    if not B.ok(doi, w.get('publication_date'), title=w.get('title')): return None
    return {'id': f'doi:{doi}' if doi else w['id'].rsplit('/', 1)[-1], 'title': w.get('title'), 'year': w.get('publication_year'),
            'journal': ((w.get('primary_location') or {}).get('source') or {}).get('display_name'), 'type': w.get('type')}


OASEL = 'id,doi,title,publication_date,publication_year,primary_location,type'


def oa_key():
    k = live_key('OPENALEX_KEY')
    return '&api_key=' + urllib.parse.quote(k) if k else ''


def search_openalex(q, n, B, filt=''):
    try: return _search_openalex(q, n, B, filt)
    except Exception as e:
        if filt or not q: raise
        out, tot = search_crossref(q, n, B)
        return out, f'OpenAlex unavailable ({str(e)[:40]}): Crossref fallback, total {tot}'


def _search_openalex(q, n, B, filt=''):
    since = f',from_publication_date:{B.start}' if B.since else ''
    url = (f'https://api.openalex.org/works?per_page={n}&select={OASEL}&filter=to_publication_date:{B.eve}{since}{filt}'
           + ('&search=' + urllib.parse.quote(q) if q else '') + oa_key())
    r = jget(url)
    return crossref_deposit([x for x in (oa_item(w, B) for w in r.get('results', [])) if x], B), r.get('meta', {}).get('count')


def oa_work(ident):
    if ident.lower().startswith('arxiv:'): ident = 'doi:10.48550/arXiv.' + ident[6:]
    if ident.startswith('doi:'): return jget('https://api.openalex.org/works/doi:' + urllib.parse.quote(ident[4:]) + ('?' + oa_key()[1:] if oa_key() else ''))
    if ident.startswith('pmid:'): return jget('https://api.openalex.org/works/pmid:' + ident[5:])
    return jget('https://api.openalex.org/works/' + ident)


def _references_openalex(w, n, B):
    rr = [x.rsplit('/', 1)[-1] for x in w.get('referenced_works', [])][:100]
    out = []
    for i in range(0, len(rr), 50):
        v = jget(f'https://api.openalex.org/works?per_page=50&select={OASEL}&filter=openalex_id:' + '|'.join(rr[i:i + 50]) + oa_key())
        out += [x for x in (oa_item(y, B) for y in v.get('results', [])) if x]
    return crossref_deposit(out, B), len(rr)


def check_key(state):
    """Live check of OPENALEX_KEY (setup_keys.py): one minimal search through fetch (a rejected key is retried without it and named)."""
    jget('https://api.openalex.org/works?per_page=1&select=id&search=test' + oa_key())
    return 'refused' if 'OPENALEX_KEY' in sc.invalid_keys(STATE) else 'ok'


SOURCE = {
    'name': 'openalex', 'order': 10,
    'engines': {'openalex': search_openalex},
    'plugins': ('biology', 'cs-ai', 'finance', 'law'), 'access': 'api',
    'hosts': {'api.openalex.org': {'interval': 0.2, 'stop': (429,)}},
    'terms': 'OpenAlex API, data CC0; key optional',
    'barrier': 'provider side: to_publication_date = eve of T (from_publication_date with since); local: publication date < T, then every DOI '
               'rechecked on Crossref (deposit AND publication < T; no Crossref DOI -> refused)',
    'key': {'vars': ('OPENALEX_KEY',), 'send': 'query:api_key', 'hosts': ('api.openalex.org',), 'without': 'degraded',
            'reason': 'budget shared per IP, 429 possible from the 1st call -> Crossref fallback flagged', 'free': 'free, personal account',
            'url': 'https://openalex.org/signup (Settings -> API key)', 'suggest': ('OpenAlex', '~2 min', True), 'labels': ['OpenAlex'], 'check': check_key,
            'rejected': {'codes': (401, 403), 'markers': (b'',)}},
}
