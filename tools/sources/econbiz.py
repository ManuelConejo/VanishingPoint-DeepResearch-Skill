# SPDX-License-Identifier: Apache-2.0
"""EconBiz (ZBW, Solr API, keyless): search-econbiz, read econbiz:<id>."""
import re
import urllib.error, urllib.parse, urllib.request
from sources._common import extra_ok, jget, year_before_T
from sources.crossref import doi_recheck
from sources._common import EXTRA_NO_CHAIN, RELATED_ONLY, value


ECONBIZ = 'https://api.econbiz.de/v1/'
MONTHS = {m: i + 1 for i, ms in enumerate(('jan january januar', 'feb february februar', 'mar march märz marz', 'apr april', 'may mai', 'jun june juni',
                                            'jul july juli', 'aug august', 'sep sept september', 'oct okt october oktober', 'nov november', 'dec dez december dezember'))
          for m in ms.split()}   # English and German month names (EconBiz records both), whole words only


def econbiz_date(s):
    """EconBiz free-text date -> partial ISO (latest date of an interval): '2018-08-03', '6 May 2026', '27. April 2017', 'January 2026',
    '1st quarter 2026', '[2015]' -> '2015'. No precision is fabricated; None when no year."""
    s = str(s or '')
    iso = re.findall(r'(\d{4})-(\d{2})(?:-(\d{2}))?', s)
    if iso: return max('-'.join(x for x in t if x) for t in iso)
    y = re.findall(r'(?<!\d)(1[5-9]\d{2}|20\d{2})(?!\d)', s)
    if not y: return None
    q = re.search(r'(\d)\s*(?:st|nd|rd|th)?\.?\s*(?:quarter|quartal)', s, re.I)
    m = next((MONTHS[w.lower()] for w in re.findall(r'[A-Za-zä]+', s) if w.lower() in MONTHS), None) or (int(q.group(1)) * 3 if q and 1 <= int(q.group(1)) <= 4 else None)
    dd = re.search(r'(?<!\d)(\d{1,2})\.?\s+[A-Za-zä]+\s+\d{4}', s) if m and not q else None
    return max(y) + (f'-{m:02d}' + (f'-{int(dd.group(1)):02d}' if dd else '') if m else '')


def econbiz_item(h, B, with_abstract=False):
    """Barrier: date of the work (year only -> year_before_T) AND date of indexing in EconBiz (econbiz_created) < T; DOI -> Crossref recheck."""
    d = econbiz_date(' '.join(h.get('date') or [])); title = h.get('title')
    doi = next((u.split('doi.org/', 1)[1] for u in h.get('identifier_url') or [] if 'doi.org/10.' in u), None)
    if not h.get('id') or not extra_ok(B, [doi, h['id'], 'econbiz:' + h['id']], [year_before_T(d, B) if d and len(d) == 4 else d, h.get('econbiz_created')], [title]): return None
    it = {'id': f'doi:{doi}' if doi else 'econbiz:' + h['id'], 'econbiz': h['id'], 'doi': doi, 'title': title, 'year': d[:4], 'date': d,
          'date_indexed': (h.get('econbiz_created') or '')[:10], 'journal': '; '.join((h.get('isPartOf') or h.get('series') or h.get('publisher') or [])[:1]) or None,
          'first_author': ((h.get('creator') or h.get('person') or [None])[0]), 'type': ', '.join(h.get('type_genre') or [h.get('type') or '']) or None,
          'url': 'https://www.econbiz.de/Record/' + h['id']}
    if with_abstract: it['abstract'] = ' '.join(' '.join(h.get('abstract') or []).split())[:6000] or 'subjects: ' + '; '.join(h.get('subject') or [])[:2000]
    return it


def search_econbiz(q, n, B):
    """EconBiz (ZBW, keyless; Solr): indexing date and year bounded on the provider side (econbiz_created <= eve of T, date_sort <= its year)."""
    lo = B.since or '*'
    qq = f'({q}) AND econbiz_created:[* TO {B.eve}T23:59:59Z] AND date_sort:[{lo} TO {B.eve.year}]'
    r = jget(ECONBIZ + 'search?' + urllib.parse.urlencode({'q': qq, 'size': n}))['hits']
    out = list({x['id']: x for x in (econbiz_item(h, B) for h in r.get('hits', [])) if x}.values())   # one entry per identifier
    return doi_recheck(out, B), r.get('total')


def read_econbiz(ident, B):
    if not re.fullmatch(r'\d{6,14}', ident): return {'refusal': 'expected form econbiz:<record id>, e.g. econbiz:10011386660'}
    try: rec = jget(ECONBIZ + 'record/' + ident).get('record')
    except urllib.error.HTTPError as e:
        if e.code in (400, 404): return {'refusal': 'not found'}
        raise
    it = econbiz_item(rec or {}, B, with_abstract=True)
    return (doi_recheck([it], B) or [{'refusal': 'deposit not attested by Crossref'}])[0] if it else {'refusal': 'not found, after T or forbidden'}


def read_econbiz_ident(ident, B): return read_econbiz(value(ident), B)


SOURCE = {
    'name': 'econbiz', 'order': 110,
    'engines': {'econbiz': search_econbiz},
    'ids': [{'prefix': 'econbiz', 'form': r'\d+', 'export': 'article', 'export_rank': 110}],
    'read': read_econbiz_ident, 'citing': EXTRA_NO_CHAIN, 'references': EXTRA_NO_CHAIN, 'related': RELATED_ONLY,
    'plugins': ('finance',), 'access': 'api',
    'hosts': {'api.econbiz.de': {'interval': 1.0, 'stop': (429,)}},
    'terms': 'EconBiz API (ZBW), keyless',
    'barrier': 'provider side: econbiz_created <= eve of T and date_sort <= its year; local: date of the work (year only: strictly before the year of T) AND indexing date < T, DOIs rechecked on Crossref',
}
