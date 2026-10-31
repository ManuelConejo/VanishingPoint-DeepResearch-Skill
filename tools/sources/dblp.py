# SPDX-License-Identifier: Apache-2.0
"""dblp through its SPARQL endpoint (QLever): search-dblp, read dblp:<key>."""
import hashlib
import json
import re
import urllib.error, urllib.parse, urllib.request
from sources._common import ProviderError, STATE, arxiv_month, extra_ok, fetch, year_before_T
from sources.crossref import doi_recheck
from sources._common import EXTRA_NO_CHAIN, RELATED_ONLY, value


DBLP_SPARQL = 'https://sparql.dblp.org/sparql'
DBLP_PRE = ('PREFIX dblp: <https://dblp.org/rdf/schema#>\nPREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\nPREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n'
            'PREFIX ql: <http://qlever.cs.uni-freiburg.de/builtin-functions/>\n')


def dblp_rows(q):
    """dblp SPARQL (QLever, keyless). The search API dblp.org/search answers an Anubis anti-robot page (HTTP 202): not used (ACCESS-POLICY.md).
    429 -> rate_limited with the Retry-After asked (no retry); a non-JSON answer -> bot_challenge, never an empty result."""
    url = DBLP_SPARQL + '?' + urllib.parse.urlencode({'query': q})
    try: raw = fetch(url, headers={'Accept': 'application/sparql-results+json'})
    except urllib.error.HTTPError as e:
        if e.code == 429 and b'timed out' in (e.read() or b'')[:400]: raise ProviderError('provider_error: dblp query timed out on the server (not an empty result)')
        if e.code == 429: raise ProviderError(f"rate_limited: dblp asks to wait {e.headers.get('Retry-After') or 'unspecified'} s (no retry)")
        raise
    try: r = json.loads(raw)
    except ValueError:                                                  # an anti-robot page is never kept in the cache as an answer
        (STATE / 'cache' / hashlib.sha256((url + json.dumps({'Accept': 'application/sparql-results+json'}, sort_keys=True)).encode()).hexdigest()).unlink(missing_ok=True)
        raise ProviderError('bot_challenge: dblp answered a non-JSON page (not an empty result)')
    return [{k: v.get('value') for k, v in b.items()} for b in r.get('results', {}).get('bindings', [])]


def dblp_items(rows, B, limit=100):
    """Rows grouped per record. dblp has only years: every year (publication, event) strictly before the year of T (year_before_T);
    a CoRR record is dated by its arXiv identifier (month of v1 < T); any other DOI is rechecked on Crossref (doi_recheck)."""
    recs = {}
    for r in rows:
        x = recs.setdefault(r['p'], {'years': set(), 'doi': None, 'venue': None, 'title': r.get('title'), 'label': r.get('label')})
        x['years'] |= {r[k] for k in ('year', 'ev') if r.get(k)}
        x['doi'] = x['doi'] or (r.get('doi') or '').replace('https://doi.org/', '') or None; x['venue'] = x['venue'] or r.get('venue')
    out = []
    for p, x in recs.items():
        key_ = p.removeprefix('https://dblp.org/rec/'); doi = x['doi']
        ax = re.match(r'(?i)10\.48550/arxiv\.(.+)', doi or '')
        dates = [arxiv_month(ax.group(1))] if ax else [year_before_T(y, B) for y in sorted(x['years'])]
        if not extra_ok(B, [doi, key_, 'dblp:' + key_], dates or [None], [x['title']]): continue
        out.append({'id': f'arxiv:{ax.group(1)}' if ax else f'doi:{doi}' if doi else f'dblp:{key_}', 'dblp': key_, 'doi': None if ax else doi,
                    'title': x['title'], 'year': max(x['years']) if x['years'] else None, 'journal': x['venue'], 'type': 'publication',
                    'first_author': (x['label'] or '').split(':', 1)[0].split(',')[0].removesuffix(' et al.') or None})
    return doi_recheck(out[:limit], B)                                  # Crossref recheck bounded to the head of the list (calls)


DBLP_SELECT = 'SELECT ?p ?title ?year ?ev ?doi ?venue ?label WHERE { ?p dblp:title ?title ; dblp:yearOfPublication ?year .\n'
DBLP_OPT = 'OPTIONAL { ?p dblp:yearOfEvent ?ev } OPTIONAL { ?p dblp:doi ?doi } OPTIONAL { ?p dblp:publishedIn ?venue } OPTIONAL { ?p rdfs:label ?label }\n'


def search_dblp(q, n, B):
    """dblp through its SPARQL endpoint (QLever title word index ql:contains-word: every word of 3 letters or more, at most 6, `word*` = prefix;
    a CONTAINS(LCASE()) scan with ORDER BY takes 14-25 s, measured 2026-10-28); year bounded on the provider side (year < year of T);
    most recent first, LIMIT 100 rows, grouped and rechecked locally."""
    words = [w for w in re.findall(r'\w+\*?', q.lower()) if len(w.rstrip('*')) >= 3][:6]
    if not words: return [], 'no usable title word (3 letters or more)'
    since = f' && ?year >= "{B.since}"^^xsd:gYear' if B.since else ''
    sq = (DBLP_PRE + DBLP_SELECT + '?t ql:contains-entity ?title . ' + ' '.join(f'?t ql:contains-word "{w}" .' for w in words)
          + f'\nFILTER(?year < "{B.T.year}"^^xsd:gYear{since})\n' + DBLP_OPT + '} ORDER BY DESC(?year) LIMIT 100')
    rows = dblp_rows(sq)
    return dblp_items(rows, B, 2 * n)[:n], f'bounded: {len(rows)} rows (LIMIT 100, most recent year first); dblp gives no count nor relevance'


def read_dblp(key_, B):
    if not re.fullmatch(r'[a-z]+(/[\w.+-]+){1,4}', key_): return {'refusal': 'expected form dblp:<record key>, e.g. dblp:conf/acl/Xiong0LZ24'}
    p = f'<https://dblp.org/rec/{key_}>'
    rows = dblp_rows(DBLP_PRE + f'SELECT ?title ?year ?ev ?doi ?venue ?label WHERE {{ {p} dblp:title ?title ; dblp:yearOfPublication ?year .\n' + DBLP_OPT.replace('?p ', p + ' ') + '}')
    items = dblp_items([dict(r, p='https://dblp.org/rec/' + key_) for r in rows], B)
    return dict(items[0], abstract='(dblp holds no abstract: read the DOI or arXiv identifier)') if items else {'refusal': 'not found, after T, forbidden or deposit not attested'}


def read_dblp_ident(ident, B): return read_dblp(value(ident), B)


SOURCE = {
    'name': 'dblp', 'order': 100,
    'engines': {'dblp': search_dblp},
    'ids': [{'prefix': 'dblp', 'form': r'[\w-]+(/[\w.:+-]+)+', 'export': 'article', 'export_rank': 110}],
    'read': read_dblp_ident, 'citing': EXTRA_NO_CHAIN, 'references': EXTRA_NO_CHAIN, 'related': RELATED_ONLY,
    'plugins': ('cs-ai',), 'access': 'api',
    'hosts': {'sparql.dblp.org': {'interval': 2.0, 'stop': (403, 429, 'timeout')}},
    'terms': 'dblp data CC0; SPARQL endpoint keyless',
    'barrier': 'provider side: year < year of T; local: every year (publication, event) strictly before the year of T (arXiv month for arXiv ids), DOIs rechecked on Crossref',
}
