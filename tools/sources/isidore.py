# SPDX-License-Identifier: Apache-2.0
"""Isidore (Huma-Num, CNRS): French-speaking humanities and social sciences aggregator (HAL SHS, OpenEdition, Persee, theses, Cairn
metadata...), documented keyless API: search-isidore, read isidore:<Isidore URI>."""
import re
import urllib.parse
from sources._common import extra_ok, jget, value, year_before_T
from sources._common import EXTRA_NO_CHAIN, RELATED_ONLY
from sources.crossref import doi_recheck

ISIDORE = 'https://api.isidore.science/resource/search'
ISIDORE_MAX = 1000          # provider maximum of `replies` per request (API page)
ISIDORE_OVERFETCH = 3       # rows asked per wanted result: the API filters by year only, the barrier is applied locally
ISIDORE_ABSTRACT = 6000     # characters of abstract served
ISIDORE_URI = r'\d+(\.\d+)*/[0-9A-Za-z][0-9A-Za-z.]{2,80}'      # handle-like URIs: 10670/1.3904e8de..., 20.500.13089/16ds9
DOI = re.compile(r'^https?://(dx\.)?doi\.org/(10\.\d{4,9}/\S+)$', re.I)


def _list(x): return x if isinstance(x, list) else [x] if x is not None else []


def _text(x):
    """Isidore value -> string ({'$': ...} or plain)."""
    return ' '.join(str(x.get('$') if isinstance(x, dict) else x).split()) if x is not None else None


def _pick(values, langs=('fr', 'en')):
    vals = [v for v in _list(values) if not (isinstance(v, dict) and v.get('@added') == 'true')] or _list(values)
    for lang in langs:
        v = next((v for v in vals if isinstance(v, dict) and v.get('@xml:lang') == lang), None)
        if v is not None: return _text(v)
    return next((_text(v) for v in vals if _text(v)), None)


def isidore_item(reply, B, with_abstract=False):
    """One reply -> the item served, or None (barrier). Date: the record's date (`date.@origin`); a year alone passes only when strictly
    before the year of T (year_before_T); a full or partial date is read as its upper bound. No date -> refused. Isidore exposes no
    indexing date; items carrying a DOI pass only when Crossref attests deposit AND publication before T."""
    uri, r = reply.get('@uri'), reply.get('isidore') or {}
    d = r.get('date') or {}
    origin = str(d.get('@origin') or '').strip() if isinstance(d, dict) else ''
    date = year_before_T(origin, B) if re.fullmatch(r'\d{4}', origin) else (origin or None)
    url = _text(r.get('url'))
    m = DOI.match(url or '')
    doi = m.group(2) if m else None
    title = _pick(r.get('title'))
    if not uri or not extra_ok(B, [doi, uri, 'isidore:' + uri], [date], [title]): return None
    types = [_text(t) for t in _list((r.get('types') or {}).get('type'))]
    src = r.get('source') or {}
    it = {'id': 'isidore:' + uri, 'isidore': uri, 'doi': doi, 'title': title, 'year': origin[:4], 'date': origin,
          'first_author': _text(((_list((r.get('enrichedCreators') or {}).get('creator')) or [{}])[0] or {}).get('@origin')),
          'journal': 'Isidore' + (f" ({_text(src.get('shortName')) or _pick(src.get('name'))})" if src else ''), 'url': url,
          'type': 'thesis' if any('thesis' in (t or '').lower() or 'these' in (t or '').lower() for t in types) else 'article',
          'types': [t for t in types if t], 'rights': _text(r.get('dc:rights')) if not isinstance(r.get('dc:rights'), list) else [_text(x) for x in r['dc:rights']],
          'tier': 'secondary', 'order': None}
    if with_abstract:
        it['abstract'] = (_pick([a for a in _list(r.get('abstract')) if isinstance(a, dict)]) or '(no abstract available)')[:ISIDORE_ABSTRACT]
    return it


def _replies(r): return _list((((r.get('response') or {}).get('replies') or {}).get('content') or {}).get('reply'))


def search_isidore(q, n, B):
    """Isidore search (relevance order). The API has a year filter but no date range: rows are asked with an over-fetch and the barrier is
    applied locally on every record (no provider-side filter at the eve of T is possible)."""
    if not (q or '').strip(): return [], 'empty query'
    r = jget(ISIDORE + '?' + urllib.parse.urlencode({'q': q, 'output': 'json', 'replies': min(ISIDORE_MAX, n * ISIDORE_OVERFETCH)}))
    out = [x for x in (isidore_item(x, B) for x in _replies(r)) if x]
    tot = (((r.get('response') or {}).get('replies') or {}).get('meta') or {}).get('@items')
    return doi_recheck(out, B)[:n], f'provider announces {tot} (all dates); no date range on the provider side: barrier applied locally'


def read_isidore_uri(uri, B):
    if not re.fullmatch(ISIDORE_URI, uri): return {'refusal': 'expected form isidore:<Isidore URI>, e.g. isidore:10670/1.3904e8dea2beef818dcfe30152cf9d7bde121ebc'}
    rs = [x for x in _replies(jget(ISIDORE + '?' + urllib.parse.urlencode({'uri': uri, 'output': 'json', 'replies': 1}))) if x.get('@uri') == uri]
    if not rs: return {'refusal': 'not found'}
    it = isidore_item(rs[0], B, with_abstract=True)
    if not it: return {'refusal': 'after T, forbidden or undated'}
    if it['doi'] and not doi_recheck([it], B): return {'refusal': 'DOI not attested by Crossref before T'}
    return it


def read_isidore(ident, B): return read_isidore_uri(value(ident), B)


SOURCE = {
    'name': 'isidore', 'order': 75,
    'engines': {'isidore': search_isidore},
    'ids': [{'prefix': 'isidore', 'form': ISIDORE_URI, 'law_form': ISIDORE_URI, 'export': 'article', 'export_rank': 105}],
    'read': read_isidore, 'citing': EXTRA_NO_CHAIN, 'references': EXTRA_NO_CHAIN, 'related': RELATED_ONLY,
    'plugins': ('law',), 'access': 'api',
    'hosts': {'api.isidore.science': {'interval': 15.0, 'timeout': 60, 'stop': (403, 429)}},   # robots.txt Crawl-delay 15
    'terms': 'Isidore API (https://isidore.science/api), keyless; CGU of 23/01/2026 (https://isidore.science/cgu): no substantial extraction '
             'or re-use of the database (CNRS sui generis right), no commercial use without written permission, no intensive use of bots; '
             'no clause on AI use; records keep the licence of their provider (dc:rights)',
    'barrier': 'provider side: none (year filter only, no range); local: record date < T (year alone: strictly before the year of T); no date '
               '-> refused; no indexing date exposed; DOIs rechecked on Crossref',
    'key': None,
}
