# SPDX-License-Identifier: Apache-2.0
"""HAL (CCSD search API): search-hal (law domain), search-hal-info (computer science and statistics), read hal:<id>."""
import re
import urllib.error, urllib.parse, urllib.request
from sources._common import jget, law_ok
from sources._common import LAW_NO_CHAIN, RELATED_ONLY, preprint_unless_venue, value


HAL = 'https://api.archives-ouvertes.fr/search/'
HAL_FL = 'halId_s,title_s,producedDate_s,submittedDate_s,doiId_s,uri_s,docType_s,authFullName_s'


def hal_item(d, B, with_abstract=False):
    title = (d.get('title_s') or [None])[0]
    # production date AND deposit date < T (a 2018 work deposited in 2020 is refused for T in 2019)
    if not law_ok(B, [d.get('doiId_s'), d.get('halId_s'), 'hal:' + str(d.get('halId_s'))], [d.get('producedDate_s'), d.get('submittedDate_s')], d.get('title_s') or []): return None
    it = {'id': 'hal:' + d['halId_s'], 'hal': d['halId_s'], 'doi': d.get('doiId_s'), 'title': title, 'year': (d.get('producedDate_s') or '')[:4],
          'date': d.get('producedDate_s'), 'date_deposited': (d.get('submittedDate_s') or '')[:10], 'journal': 'HAL (law)',
          'first_author': (d.get('authFullName_s') or [None])[0], 'type': d.get('docType_s'), 'url': d.get('uri_s'), 'tier': 'secondary', 'order': None}
    if with_abstract: it['abstract'] = ' '.join(' '.join(d.get('abstract_s') or ['(no abstract available)']).split())[:6000]
    return it


def search_hal(q, n, B):
    """HAL, law domain (level1_domain_s:shs.droit; domain_s returns 0): production and deposit dates bounded on the server to the eve of T."""
    rng = f'[{B.start}T00:00:00Z TO {B.eve}T23:59:59Z]'
    r = jget(HAL + '?' + urllib.parse.urlencode([('q', q or '*:*'), ('fq', 'level1_domain_s:shs.droit'), ('fq', 'producedDate_tdate:' + rng),
                                                 ('fq', 'submittedDate_tdate:' + rng), ('wt', 'json'), ('fl', HAL_FL), ('rows', n)]))['response']
    return [x for x in (hal_item(d, B) for d in r.get('docs', [])) if x], r.get('numFound')


def read_hal(hid, B):
    if not re.fullmatch(r'[a-z]+-\d+', hid): return {'refusal': 'expected form hal:<halId>, e.g. hal:hal-01891420'}
    docs = jget(HAL + '?' + urllib.parse.urlencode([('q', f'halId_s:{hid}'), ('wt', 'json'), ('fl', HAL_FL + ',abstract_s'), ('rows', 1)]))['response'].get('docs', [])
    if not docs: return {'refusal': 'not found'}
    return hal_item(docs[0], B, with_abstract=True) or {'refusal': 'after T or forbidden'}


def search_hal_info(q, n, B):
    """HAL, computer science and statistics (level0_domain_s info or stat; no law restriction): same server bounds and barrier as search_hal."""
    rng = f'[{B.start}T00:00:00Z TO {B.eve}T23:59:59Z]'
    r = jget(HAL + '?' + urllib.parse.urlencode([('q', q or '*:*'), ('fq', 'level0_domain_s:(info OR stat)'), ('fq', 'producedDate_tdate:' + rng),
                                                 ('fq', 'submittedDate_tdate:' + rng), ('wt', 'json'), ('fl', HAL_FL), ('rows', n)]))['response']
    return [dict(x, journal='HAL') for x in (hal_item(d, B) for d in r.get('docs', [])) if x], r.get('numFound')


def read_hal_ident(ident, B): return read_hal(value(ident), B)


SOURCE = {
    'name': 'hal', 'order': 70,
    'engines': {'hal': search_hal, 'hal-info': search_hal_info},
    'ids': [{'prefix': 'hal', 'form': r'[a-z]+-\d+(v\d+)?', 'law_form': r'[a-z]+-\d+', 'export': preprint_unless_venue, 'export_rank': 100}],
    'read': read_hal_ident, 'citing': LAW_NO_CHAIN, 'references': LAW_NO_CHAIN, 'related': RELATED_ONLY,
    'plugins': ('law', 'cs-ai'), 'access': 'api',
    'hosts': {'api.archives-ouvertes.fr': {'interval': 1.0, 'stop': (400,)}},
    'terms': 'HAL public search API (CCSD), documented, keyless',
    'barrier': 'provider side: production AND deposit dates bounded to [start, eve of T]; local: both dates < T (a work deposited after T is refused)',
}
