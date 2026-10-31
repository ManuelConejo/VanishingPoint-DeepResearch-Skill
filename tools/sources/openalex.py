# SPDX-License-Identifier: Apache-2.0
"""OpenAlex: search-openalex (Crossref fallback when OpenAlex fails), related works and reference lists for the DOI chaining; arXiv works
served as arxiv:<id> (oa_item).
Optional OPENALEX_KEY (api_key=, own budget instead of the per-IP one)."""
import re
import urllib.error, urllib.parse, urllib.request
from sources._common import ARXIV_DOI, CFG, arxiv_id, arxiv_month, extra_ok, jget, live_key
from sources.crossref import crossref_deposit, search_crossref
import code_sources as sc
from sources._common import STATE


def oa_item(w, B):
    """A work under the local barrier. An arXiv work (DataCite DOI 10.48550/arXiv.<id>, or no DOI and an arXiv landing page) has no Crossref
    deposit to recheck: it is served as arxiv:<id>, dated by its OpenAlex publication date AND the month of v1 encoded in the identifier
    (the rule of dblp CoRR records); forbidden as DOI, arxiv:<id> or bare id. Any other work: publication date < T, Crossref recheck after."""
    doi = (w.get('doi') or '').replace('https://doi.org/', '') or None
    ax = arxiv_id(doi) if doi else arxiv_id((w.get('primary_location') or {}).get('landing_page_url'))
    if ax:
        # forbidden also as a venue DOI OpenAlex lists among the work's locations (journal or proceedings version of the preprint); the venue
        # DOI that arXiv itself records (<arxiv:doi>) is checked after, in one batch per page (crossref_deposit -> sources.arxiv.arxiv_recheck)
        if not extra_ok(B, [doi, ARXIV_DOI + ax, 'arxiv:' + ax, ax] + location_dois(w), [w.get('publication_date'), arxiv_month(ax)], [w.get('title')]): return None
        return {'id': f'arxiv:{ax}', 'arxiv': ax, 'title': w.get('title'), 'year': w.get('publication_year'),
                'journal': ((w.get('primary_location') or {}).get('source') or {}).get('display_name'), 'type': w.get('type')}
    if not B.ok(doi, w.get('publication_date'), title=w.get('title')): return None
    return {'id': f'doi:{doi}' if doi else w['id'].rsplit('/', 1)[-1], 'title': w.get('title'), 'year': w.get('publication_year'),
            'journal': ((w.get('primary_location') or {}).get('source') or {}).get('display_name'), 'type': w.get('type')}


OASEL = 'id,doi,title,publication_date,publication_year,primary_location,locations,type'


def location_dois(w):
    """DOIs named by the landing pages of an OpenAlex work's locations (doi.org URLs), e.g. the journal version of an arXiv preprint."""
    return [m.group(1) for loc in (w.get('locations') or []) if isinstance(loc, dict)
            for m in [re.match(r'(?i)https?://(?:dx\.)?doi\.org/(10\..+)$', str(loc.get('landing_page_url') or '').strip())] if m]


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
    """Pages until n works pass the local barrier (date, forbidden DOI/title, Crossref deposit recheck) or OpenAlex is exhausted,
    at most oversample.openalex_extra_pages pages beyond the first (config.json): the barrier filters after paging, so one page of n
    usually yields fewer than n."""
    since = f',from_publication_date:{B.start}' if B.since else ''
    base = (f'https://api.openalex.org/works?per_page={n}&select={OASEL}&filter=to_publication_date:{B.eve}{since}{filt}'
            + ('&search=' + urllib.parse.quote(q) if q else '') + oa_key())
    out, seen, total = [], set(), None
    for page in range(1, 2 + max(0, int(CFG['oversample']['openalex_extra_pages']))):
        r = jget(base + (f'&page={page}' if page > 1 else ''))   # page 1 keeps the v0.6.0 URL (cache and fixtures unchanged)
        total = r.get('meta', {}).get('count') if total is None else total
        works = r.get('results', [])
        for x in crossref_deposit([x for x in (oa_item(w, B) for w in works) if x], B):
            if x['id'] not in seen: seen.add(x['id']); out.append(x)
        if len(out) >= n or len(works) < n or (total is not None and page * n >= total): break
    return out[:n], total


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
               'rechecked on Crossref (deposit AND publication < T; no Crossref DOI -> refused), except an arXiv work (DOI 10.48550/arXiv.<id> or '
               'arXiv landing page): served as arxiv:<id>, publication date AND month of v1 of the identifier < T, and refused when a venue DOI of '
               'the work (OpenAlex locations, or the DOI arXiv records for it, one arXiv batch per page; no arXiv record -> refused) is forbidden',
    'key': {'vars': ('OPENALEX_KEY',), 'send': 'query:api_key', 'hosts': ('api.openalex.org',), 'without': 'degraded',
            'reason': 'budget shared per IP, 429 possible from the 1st call -> Crossref fallback flagged', 'free': 'free, personal account',
            'url': 'https://openalex.org/signup (Settings -> API key)', 'suggest': ('OpenAlex', '~2 min', True), 'labels': ['OpenAlex'], 'check': check_key,
            'rejected': {'codes': (401, 403), 'markers': (b'',)}},
}
