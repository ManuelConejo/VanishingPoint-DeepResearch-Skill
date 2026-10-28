# SPDX-License-Identifier: Apache-2.0
"""DataCite REST API (keyless, metadata CC0): search-datacite "<words> [type:dataset|software|...]" -> DOIs of datasets, software and
other DataCite works (absent from Crossref and OpenAlex), dated before T. Identity: `doi:<DOI>` (SKILL.md: one document, one identifier);
`read doi:<DataCite DOI>` reaches datacite_read through the default DOI source when Crossref does not know the DOI."""
import html
import re
import urllib.error, urllib.parse
from sources._common import _before, extra_ok, jget

API = 'https://api.datacite.org/dois'
TYPES = ('audiovisual', 'book', 'book-chapter', 'collection', 'computational-notebook', 'conference-paper', 'data-paper', 'dataset',
         'dissertation', 'event', 'image', 'instrument', 'interactive-resource', 'journal-article', 'model', 'output-management-plan',
         'peer-review', 'physical-object', 'preprint', 'report', 'service', 'software', 'sound', 'standard', 'text', 'workflow', 'other')


def issued(a):
    """Publication date of a DataCite record: the full `Issued` date when present, else the publication year (never made more precise)."""
    d = next((x.get('date') for x in a.get('dates') or [] if (x.get('dateType') or '').lower() == 'issued' and x.get('date')), None)
    return d or (str(a['publicationYear']) if a.get('publicationYear') else None)


def dc_item(x, B, with_abstract=False):
    """DataCite record -> item, or None: issued (or year), created AND registered < T (no date -> refused); DOI, related identifiers and
    title checked against the forbidden lists. Metadata updated on/after T: description masked, title as now (flagged). Counts (views,
    downloads, citations) and the current state are never served (post-T knowledge)."""
    a = x.get('attributes') or {}; doi = a.get('doi') or x.get('id')
    title = ((a.get('titles') or [{}])[0] or {}).get('title')
    ids = [doi, 'doi:' + str(doi)] + [r.get('relatedIdentifier') for r in a.get('relatedIdentifiers') or []]
    if not doi or not extra_ok(B, ids, [issued(a), a.get('created'), a.get('registered')], [title]): return None
    fresh = bool(_before(a.get('updated'), B))
    t = a.get('types') or {}
    it = {'id': 'doi:' + doi, 'doi': doi, 'title': title, 'year': str(a.get('publicationYear') or ''), 'date': issued(a),
          'date_registered': str(a.get('registered'))[:10], 'journal': a.get('publisher') if isinstance(a.get('publisher'), str) else (a.get('publisher') or {}).get('name'),
          'type': (t.get('resourceTypeGeneral') or '').lower() or None, 'first_author': ((a.get('creators') or [{}])[0] or {}).get('name'),
          'version': a.get('version') if fresh else None, 'url': 'https://doi.org/' + doi, 'source': 'DataCite',
          'metadata': 'unchanged since before T' if fresh else 'updated on/after T: description and version masked, title as now'}
    if with_abstract:
        d = next((y.get('description') for y in a.get('descriptions') or [] if y.get('description')), None)
        it['abstract'] = ' '.join(html.unescape(re.sub('<[^>]+>', ' ', d or '(no description available)')).split())[:6000] if fresh \
            else '(masked: metadata updated on/after T)'
    return it


def search_datacite(q, n, B):
    """Provider side: created AND registered in [start, eve of T] in the query; optional `type:<resource type>` word; local recheck of
    issued, created and registered (dc_item)."""
    words, rt = [], None
    for w in str(q or '').split():
        m = re.fullmatch(r'type:([a-z-]+)', w.lower())
        if m and m.group(1) in TYPES: rt = m.group(1)
        else: words.append(w)
    text = ' '.join(words).strip() or '*'
    qq = f'({text}) AND created:[{B.start} TO {B.eve}] AND registered:[{B.start} TO {B.eve}]'
    params = {'query': qq, 'page[size]': min(n, 50)}
    if rt: params['resource-type-id'] = rt
    r = jget(API + '?' + urllib.parse.urlencode(params))
    return [x for x in (dc_item(h, B) for h in r.get('data') or []) if x][:n], (r.get('meta') or {}).get('total')


def datacite_read(doi, B):
    """A DataCite DOI -> record with its description, {'refusal': ...} after T, or None when DataCite does not know the DOI."""
    try: r = jget(API + '/' + urllib.parse.quote(doi, safe='/'))
    except urllib.error.HTTPError as e:
        if e.code == 404: return None
        raise
    return dc_item(r.get('data') or {}, B, with_abstract=True) or {'refusal': 'after T, forbidden or undated (DataCite)'}


SOURCE = {
    'name': 'datacite', 'order': 145,
    'engines': {'datacite': search_datacite},
    'plugins': ('cs-ai', 'biology'), 'access': 'api',
    'hosts': {'api.datacite.org': {'interval': 1.0, 'stop': (404, 429)}},   # 500 requests / 5 min per IP without credentials (documented)
    'terms': 'DataCite REST API, public and keyless; DataCite metadata released CC0; User-Agent with contact asked for frequent use (VP_CONTACT)',
    'barrier': 'provider side: created AND registered in [start, eve of T]; local: Issued date (else publication year, upper bound), created '
               'AND registered < T; description masked when the metadata was updated on/after T',
}
