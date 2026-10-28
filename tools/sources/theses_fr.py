# SPDX-License-Identifier: Apache-2.0
"""theses.fr (ABES API v1): search-theses-fr, read thesesfr:<nnt>."""
import re
import urllib.error, urllib.parse, urllib.request
from sources._common import dmy, jget, law_ok
from sources._common import LAW_NO_CHAIN, RELATED_ONLY, value


THESES = 'https://theses.fr/api/v1/theses/'


def theses_item(t, B, with_abstract=False):
    nnt = t.get('nnt') or t.get('id'); d = dmy(t.get('dateSoutenance'))
    titles = [t.get('titrePrincipal'), t.get('titreEN')] + list((t.get('titres') or {}).values())
    if not nnt or not law_ok(B, [t.get('doi'), nnt, 'thesesfr:' + str(nnt)], [d], titles): return None   # defence date < T; not defended -> no date -> refused
    a = (t.get('auteurs') or [{}])[0]
    it = {'id': 'thesesfr:' + nnt, 'nnt': nnt, 'doi': t.get('doi'), 'title': t.get('titrePrincipal'), 'year': d[:4], 'date': d,
          'journal': 'theses.fr' + (f" ({t['etabSoutenanceN']})" if t.get('etabSoutenanceN') else ''), 'first_author': ' '.join(x for x in (a.get('prenom'), a.get('nom')) if x) or None,
          'type': 'thesis', 'discipline': t.get('discipline'), 'tier': 'secondary', 'order': None}
    if with_abstract:
        r = t.get('resumes') or {}
        it['abstract'] = ' '.join(str(r.get('fr') or r.get('en') or '(no abstract available)').split())[:6000]
    return it


def search_theses_fr(q, n, B):
    """theses.fr API v1 (ABES): defence date bounded on the provider side, dateSoutenance:[start TO eve of T]."""
    qq = f'({q or "*"}) AND dateSoutenance:[{B.start} TO {B.eve}]'
    r = jget(THESES + 'recherche/?' + urllib.parse.urlencode({'q': qq, 'nombre': n}))
    return [x for x in (theses_item(t, B) for t in r.get('theses', [])) if x], r.get('totalHits')


def read_theses_fr(nnt, B):
    if not re.fullmatch(r'[0-9]{4}[A-Z0-9]{4,12}', nnt): return {'refusal': 'expected form thesesfr:<nnt>, e.g. thesesfr:2018LIMO0025'}
    try: t = jget(THESES + 'these/' + nnt)
    except urllib.error.HTTPError as e:
        if e.code in (400, 404): return {'refusal': 'not found'}
        raise
    return theses_item(dict(t, nnt=t.get('nnt') or nnt), B, with_abstract=True) or {'refusal': 'after T, forbidden or not defended'}


def read_theses_ident(ident, B): return read_theses_fr(value(ident), B)


SOURCE = {
    'name': 'theses-fr', 'order': 80,
    'engines': {'theses-fr': search_theses_fr},
    'ids': [{'prefix': 'thesesfr', 'form': r'\d{4}[A-Z0-9]{4,12}', 'law_form': r'[0-9]{4}[A-Z0-9]{4,12}', 'export': 'thesis', 'export_rank': 40}],
    'read': read_theses_ident, 'citing': LAW_NO_CHAIN, 'references': LAW_NO_CHAIN, 'related': RELATED_ONLY,
    'plugins': ('law',), 'access': 'api',
    'hosts': {'theses.fr': {'interval': 5.0, 'stop': (403, 429)}},
    'terms': 'theses.fr API (ABES), keyless',
    'barrier': 'provider side: dateSoutenance in [start, eve of T]; local: defence date < T',
}
