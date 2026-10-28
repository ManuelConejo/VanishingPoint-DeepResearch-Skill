# SPDX-License-Identifier: Apache-2.0
"""Europe PMC (EMBL-EBI REST): search-europepmc; helpers used by the DOI chaining and the preprint servers (epmc_resolve, epmc_date).
pmcid: is a card identifier only (not read by the gateway)."""
import urllib.error, urllib.parse, urllib.request
from sources._common import jget


def epmc_item(r, B):
    if not B.ok(r.get('doi'), r.get('firstIndexDate'), r.get('firstPublicationDate') or r.get('pubYear'), title=r.get('title')):
        return None
    ident = f"pmid:{r['pmid']}" if r.get('pmid') else (f"doi:{r['doi']}" if r.get('doi') else r.get('id'))
    return {'id': ident, 'doi': r.get('doi'), 'title': r.get('title'), 'year': r.get('pubYear'), 'journal': r.get('journalTitle'),
            'first_author': (r.get('authorString') or '').split(',')[0], 'type': r.get('pubType')}


def search_europepmc(q, n, B):
    qq = f'({q}) AND FIRST_IDATE:[{B.start} TO {B.eve}]'
    r = jget('https://www.ebi.ac.uk/europepmc/webservices/rest/search?format=json&resultType=lite&pageSize=' + str(n) + '&query=' + urllib.parse.quote(qq))
    out = [x for x in (epmc_item(i, B) for i in r.get('resultList', {}).get('result', [])) if x]
    return out, r.get('hitCount')


EPMC = 'https://www.ebi.ac.uk/europepmc/webservices/rest/'


def epmc_resolve(ident, B):
    """-> (source, id, dated item) via Europe PMC; None when absent; refused when after T."""
    ident = ident.strip()
    q = f'EXT_ID:{ident.split(":")[-1]} AND SRC:MED' if ident.lower().startswith('pmid:') or ident.isdigit() else f'DOI:"{ident[4:] if ident.lower().startswith("doi:") else ident}"'
    res = jget(EPMC + 'search?format=json&resultType=lite&pageSize=1&query=' + urllib.parse.quote(q)).get('resultList', {}).get('result', [])
    if not res: return None
    return res[0]['source'], res[0]['id'], epmc_item(res[0], B)


def epmc_date(ids, B):
    """Batch recheck (indexing AND publication date < T) of MED identifiers."""
    out = []
    for i in range(0, min(len(ids), 200), 50):
        q = '(' + ' OR '.join(f'EXT_ID:{x}' for x in ids[i:i + 50]) + f') AND SRC:MED AND FIRST_IDATE:[1800-01-01 TO {B.eve}]'
        r = jget(EPMC + 'search?format=json&resultType=lite&pageSize=100&query=' + urllib.parse.quote(q))
        out += [x for x in (epmc_item(v, B) for v in r.get('resultList', {}).get('result', [])) if x]
    return out


SOURCE = {
    'name': 'europepmc', 'order': 41,
    'engines': {'europepmc': search_europepmc},
    'ids': [{'prefix': 'pmcid', 'form': r'PMC\d+', 'read': False, 'export': 'article', 'export_rank': 110}],
    'plugins': ('biology', 'cs-ai', 'finance'), 'access': 'api',
    'hosts': {'www.ebi.ac.uk': {'interval': 0.25}},
    'terms': 'Europe PMC RESTful web service (EMBL-EBI terms of use), keyless',
    'barrier': 'provider side: FIRST_IDATE in [start, eve of T]; local: first index date AND first publication date (or year) < T',
}
