# SPDX-License-Identifier: Apache-2.0
"""Zenodo REST (keyless): search-zenodo, read zenodo:<record id>."""
import html
import re
import urllib.error, urllib.parse, urllib.request
from sources._common import date_upper, jget, law_ok
from sources._common import RELATED_ONLY, value


ZENODO = 'https://zenodo.org/api/records'


def zenodo_item(h, B, with_abstract=False):
    """Zenodo record (DataCite DOI: no Crossref recheck): creation AND publication date < T; the record DOI, concept DOI and related
    identifiers checked against the forbidden list; metadata updated on/after T -> description masked (title kept, flagged)."""
    m = h.get('metadata') or {}; title = m.get('title') or h.get('title')
    ids = [h.get('doi') or m.get('doi'), h.get('conceptdoi'), 'zenodo:' + str(h.get('id'))] + [x.get('identifier') for x in m.get('related_identifiers') or []]
    if not h.get('id') or not law_ok(B, ids, [h.get('created'), m.get('publication_date')], [title]): return None
    upd = h.get('updated') or h.get('modified'); fresh = bool(upd) and date_upper(upd) is not None and date_upper(upd) < B.T
    rt = m.get('resource_type') or {}
    it = {'id': f"zenodo:{h['id']}", 'zenodo': h['id'], 'doi': h.get('doi') or m.get('doi'), 'title': title, 'year': str(m.get('publication_date'))[:4],
          'date': m.get('publication_date'), 'date_deposited': str(h.get('created'))[:10], 'journal': 'Zenodo', 'type': rt.get('subtype') or rt.get('type'),
          'first_author': ((m.get('creators') or [{}])[0]).get('name'), 'version': m.get('version'), 'licence': (m.get('license') or {}).get('id'),
          'url': (h.get('links') or {}).get('self_html'), 'metadata': 'unchanged since before T' if fresh else 'updated on/after T: description masked, title as now'}
    if with_abstract: it['abstract'] = ' '.join(html.unescape(re.sub('<[^>]+>', ' ', m.get('description') or '(no description available)')).split())[:6000] if fresh else '(masked: metadata updated on/after T)'
    return it


def search_zenodo(q, n, B):
    """Zenodo REST (keyless): creation and publication dates bounded on the provider side to [start, eve of T], every version listed."""
    qq = f'({q or "*"}) AND created:[{B.start} TO {B.eve}] AND publication_date:[{B.start} TO {B.eve}]'
    r = jget(ZENODO + '?' + urllib.parse.urlencode({'q': qq, 'size': min(n, 25), 'all_versions': 'true', 'sort': 'bestmatch'}))
    return [x for x in (zenodo_item(h, B) for h in (r.get('hits') or {}).get('hits') or []) if x], (r.get('hits') or {}).get('total')


def read_zenodo(rid, B):
    if not rid.isdigit(): return {'refusal': 'expected form zenodo:<record id>, e.g. zenodo:3689089'}
    try: h = jget(f'{ZENODO}/{rid}')
    except urllib.error.HTTPError as e:
        if e.code in (404, 410): return {'refusal': 'not found'}
        raise
    return zenodo_item(h, B, with_abstract=True) or {'refusal': 'after T or forbidden'}


def read_zenodo_ident(ident, B): return read_zenodo(value(ident), B)


SOURCE = {
    'name': 'zenodo', 'order': 140,
    'engines': {'zenodo': search_zenodo},
    'ids': [{'prefix': 'zenodo', 'form': r'\d+', 'export': 'dataset', 'export_rank': 80}],
    'read': read_zenodo_ident, 'related': RELATED_ONLY,                  # citing / references: handed to the default source (unchanged since v0.4)
    'plugins': ('cs-ai',), 'access': 'api',
    'hosts': {'zenodo.org': {'interval': 2.0, 'stop': (429,)}},             # search 30 req/min (documented)
    'terms': 'Zenodo REST API (CERN), keyless; each record under its own licence',
    'barrier': 'provider side: created and publication dates in [start, eve of T], every version listed; local: both dates < T',
}
