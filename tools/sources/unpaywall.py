# SPDX-License-Identifier: Apache-2.0
"""Unpaywall (keyless, `email=` contact required): search-unpaywall "<DOI> [<DOI> ...]" -> where the free copy of each DOI was open
before T. The full text itself is read later, version pinned before T, by tools/verifier/fetch_fulltext.py (which already used Unpaywall
downstream); the passages of the report are cut from that text (tools/passages.py). Without an e-mail address in VP_CONTACT: skipped,
not_configured, 0 request."""
import os
import re
import urllib.error, urllib.parse
import code_sources as sc
from sources._common import CFG, _before, date_upper, extra_ok, jget
from sources._series import DataSkip, data_engine
from sources.crossref import crossref_deposit

API = 'https://api.unpaywall.org/v2/'
DOI = re.compile(r'10\.\d{4,9}/\S+')
MAX_DOIS = int(CFG['linked_sources']['unpaywall_dois'])
FULLTEXT = 'tools/verifier/fetch_fulltext.py --doi <DOI> --T <T> (pins the last version before T; the verifier and passages.py read it)'


def contact():
    """The e-mail Unpaywall requires (`email=`): VP_CONTACT when it holds an address, else a not_configured skip before any request."""
    c = sc.contact()
    m = re.search(r'[^\s<>(),;:]+@[^\s<>(),;:]+\.[A-Za-z]{2,}', c)
    if not m: raise DataSkip('not_configured', 'Unpaywall requires an e-mail address in VP_CONTACT (KEYS.md, "Identification contact"); 0 request')
    return m.group(0)


def dois_of(q):
    """'doi:10.x/a, 10.y/b' -> ['10.x/a', '10.y/b'] (order kept, duplicates dropped)."""
    out = []
    for t in re.split(r'[\s,;]+', str(q or '')):
        t = re.sub(r'(?i)^(doi:|https?://(dx\.)?doi\.org/)', '', t.strip()).rstrip('.')
        if DOI.fullmatch(t) and t.lower() not in [x.lower() for x in out]: out.append(t)
    return out


def location(loc, B):
    """One open location, served only when it was open before T (`oa_date` < T); no oa_date -> not served (strict)."""
    if not _before(loc.get('oa_date'), B): return None
    return {'url_for_pdf': loc.get('url_for_pdf'), 'url_for_landing_page': loc.get('url_for_landing_page'), 'host_type': loc.get('host_type'),
            'version': loc.get('version'), 'license': loc.get('license'), 'oa_date': loc.get('oa_date'), 'repository': loc.get('repository_institution'),
            'pmh_id': loc.get('pmh_id')}


def oa_item(r, B):
    """Unpaywall record -> item, or None (barrier): published_date < T (partial date = upper bound), DOI and title not forbidden.
    Locations opened on/after T or undated are dropped and counted (`later_or_undated_copies`); is_oa / oa_status / best location are
    current values and are recomputed from the locations kept (`open_before_T`)."""
    doi = r.get('doi')
    if not doi or not extra_ok(B, [doi, 'doi:' + doi], [r.get('published_date')], [r.get('title')]): return None
    locs = [l for l in [r.get('best_oa_location')] + list(r.get('oa_locations') or []) if isinstance(l, dict)]
    seen, kept = set(), []
    for l in locs:
        k = (l.get('url_for_pdf'), l.get('url_for_landing_page'), l.get('url'))
        if k in seen: continue
        seen.add(k); x = location(l, B)
        if x: kept.append(x)
    return {'id': 'doi:' + doi, 'doi': doi, 'title': r.get('title'), 'year': str(r.get('year') or (r.get('published_date') or '')[:4]),
            'date': r.get('published_date'), 'journal': r.get('journal_name'), 'type': r.get('genre'),
            'open_before_T': bool(kept), 'oa_locations_before_T': kept, 'later_or_undated_copies': len(seen) - len(kept),
            'fulltext': FULLTEXT.replace('<DOI>', doi).replace('<T>', B.T.isoformat()),
            'note': 'open locations listed only when Unpaywall dates them (oa_date) before T; licence and version are as recorded now'}


@data_engine(True)
def search_unpaywall(q, n, B):
    """One request per DOI (at most min(n, linked_sources.unpaywall_dois)); each record dated < T and its DOI rechecked on Crossref
    (deposit AND publication < T). A DOI unknown to Unpaywall is listed under `not_found`, never as an empty success."""
    email = contact()
    dois = dois_of(q)
    if not dois: return [], 'expected one or more DOIs (10.xxxx/...), e.g. search-unpaywall "10.1038/nature12373"'
    out, missing = [], []
    for d in dois[:min(n, MAX_DOIS)]:
        try: r = jget(API + urllib.parse.quote(d, safe='/') + '?' + urllib.parse.urlencode({'email': email}))
        except urllib.error.HTTPError as e:
            if e.code in (404, 422): missing.append(d); continue
            raise
        it = oa_item(r, B)
        if it: out.append(it)
    kept = crossref_deposit(out, B) if out else []
    note = f'{len(kept)} of {len(dois[:min(n, MAX_DOIS)])} DOIs dated before T' + (f'; not found in Unpaywall: {", ".join(missing)}' if missing else '') \
        + (f'; {len(dois) - min(n, MAX_DOIS)} DOIs beyond the limit not looked up' if len(dois) > min(n, MAX_DOIS) else '')
    return kept, note


SOURCE = {
    'name': 'unpaywall', 'order': 25,
    'engines': {'unpaywall': search_unpaywall},
    'plugins': ('biology', 'cs-ai', 'finance', 'law'), 'access': 'api',
    'hosts': {'api.unpaywall.org': {'interval': 1.0, 'stop': (404, 422, 429)}},   # published limit 100,000 calls/day; 404 unknown DOI, 422 bad e-mail
    'terms': 'Unpaywall REST API (OurResearch), keyless, email= parameter required, about 100,000 calls/day; data CC0',
    'barrier': 'local: published_date < T (partial date = upper bound) and Crossref deposit AND publication < T; each open location served '
               'only when its oa_date < T (undated or later copies dropped and counted)',
}
