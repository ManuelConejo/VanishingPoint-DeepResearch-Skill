# SPDX-License-Identifier: Apache-2.0
"""Crossref REST API: search-crossref; the deposit recheck used by every source that serves DOIs (crossref_deposit, crossref_batch, doi_recheck)."""
import urllib.error, urllib.parse, urllib.request
from sources._common import _mailto, jget


def cr_item(it, B):
    issued = '-'.join(str(x) for x in ((it.get('issued', {}).get('date-parts') or [[None]])[0] or []) if x)
    if not B.ok(it.get('DOI'), issued, (it.get('created') or {}).get('date-time'), title=(it.get('title') or [''])[0]): return None
    return {'id': 'doi:' + it['DOI'], 'title': (it.get('title') or [''])[0], 'year': issued[:4],
            'journal': (it.get('container-title') or [''])[0], 'first_author': ((it.get('author') or [{}])[0]).get('family'), 'type': it.get('type')}


def search_crossref(q, n, B):
    since = f',from-pub-date:{B.start}' if B.since else ''
    url = (f'https://api.crossref.org/works?rows={n}&filter=until-created-date:{B.eve},until-pub-date:{B.eve}{since}'
           '&select=DOI,title,issued,created,container-title,author,type&query.bibliographic=' + urllib.parse.quote(q) + _mailto())
    m = jget(url)['message']
    return [x for x in (cr_item(i, B) for i in m.get('items', [])) if x], m.get('total-results')


def crossref_deposit(items, B):
    """OpenAlex has no reliable indexing date: every returned DOI is rechecked on Crossref (deposit AND publication < T).
    Without DOI, or DOI absent from Crossref: refused (strict)."""
    dois = [x['id'][4:] for x in items if x['id'].startswith('doi:')]
    ok = set()
    for i in range(0, len(dois), 40):
        f = ','.join('doi:' + x for x in dois[i:i + 40])
        m = jget('https://api.crossref.org/works?rows=100&select=DOI,title,issued,created&filter=' + urllib.parse.quote(f, safe=':,') + _mailto())['message']
        ok |= {it['DOI'].lower() for it in m.get('items', []) if cr_item(it, B)}
    kept = [x for x in items if x['id'].startswith('doi:') and x['id'][4:].lower() in ok]
    B.excluded += len(items) - len(kept)
    return kept


def crossref_batch(dois, B):
    """Dated Crossref notices (deposit AND publication < T) for a list of DOIs, in batches."""
    out = []
    for i in range(0, min(len(dois), 300), 40):
        f = ','.join('doi:' + x for x in dois[i:i + 40])
        m = jget('https://api.crossref.org/works?rows=100&select=DOI,title,issued,created,container-title,author,type&filter=' + urllib.parse.quote(f, safe=':,') + _mailto())['message']
        out += [x for x in (cr_item(it, B) for it in m.get('items', [])) if x]
    return out


def doi_recheck(items, B):
    """Items carrying a DOI pass only when Crossref attests deposit AND publication < T (crossref_deposit, strict); the others are kept."""
    withd = [x for x in items if x.get('doi')]
    ok = {x['id'][4:].lower() for x in crossref_deposit([{'id': 'doi:' + x['doi']} for x in withd], B)} if withd else set()
    return [x for x in items if not x.get('doi') or x['doi'].lower() in ok]


SOURCE = {
    'name': 'crossref', 'order': 12,
    'engines': {'crossref': search_crossref},
    'plugins': ('biology', 'cs-ai', 'finance'), 'access': 'api',
    'hosts': {'api.crossref.org': {'interval': 0.25}},
    'terms': 'Crossref REST API, metadata CC0 (abstracts excepted); polite pool with mailto=VP_CONTACT when set',
    'barrier': 'provider side: until-created-date AND until-pub-date = eve of T (from-pub-date with since); local: issued AND created (deposit) < T',
}
