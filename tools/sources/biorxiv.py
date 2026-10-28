# SPDX-License-Identifier: Apache-2.0
"""bioRxiv and medRxiv (api.biorxiv.org, keyless): search-biorxiv / search-medrxiv (Europe PMC words, each hit dated on
api.biorxiv.org), read biorxiv:<DOI> | medrxiv:<DOI> (also doi:<openRxiv preprint DOI> or the bare DOI): latest version posted before T."""
import re
import urllib.error, urllib.parse, urllib.request
from sources._common import ProviderError, _before, extra_ok, jget
from sources.crossref import crossref_batch
from sources.europepmc import EPMC
from sources.doi import citing_doi, references_doi, related_work
from sources.openalex import oa_work


RXIV = 'https://api.biorxiv.org/details/'
RXIV_SERVER = {'biorxiv': 'bioRxiv', 'medrxiv': 'medRxiv'}
RXIV_DOI = r'10\.(?:1101|64898)/(?:\d{4}\.\d{2}\.\d{2}\.)?\d{6,8}'   # openRxiv preprint DOIs (10.64898 for new posts, measured 2026-10-28); 10.1101/gad.x = CSHL journals


def rxiv_versions(server, doi):
    """Every version (sorted) of a preprint on api.biorxiv.org; [] when the server has no such post; ProviderError on any other answer."""
    r = jget(RXIV + server + '/' + doi + '/na/json')
    st = str(((r.get('messages') or [{}])[0] or {}).get('status') or '')
    if st != 'ok':
        if 'no posts' in st.lower(): return []
        raise ProviderError(f'provider_error: api.biorxiv.org answered "{st[:60]}" (not an empty result)')
    return sorted(r.get('collection') or [], key=lambda v: int(v['version']) if str(v.get('version', '')).isdigit() else 0)


def rxiv_item(server, doi, rows, B, epmc=None, with_abstract=False):
    """Barrier: preprint DOI, published-article DOI (any date) and every title (all versions, Europe PMC) against the forbidden lists; first
    version posted < T (and Europe PMC first publication and indexing < T when the hit comes from a search); no date -> refused.
    Served: the latest version posted < T; later versions are never read (later_versions_masked); published_doi set by rxiv_published."""
    pub = next((v.get('published') for v in reversed(rows) if v.get('published') not in (None, '', 'NA')), None)
    first = rows[0] if rows else {}
    dates = [first.get('date')] + ([epmc.get('firstPublicationDate'), epmc.get('firstIndexDate')] if epmc is not None else [])
    if not rows or not extra_ok(B, [doi, server + ':' + doi, pub], dates, [v.get('title') for v in rows] + [(epmc or {}).get('title')]): return None
    seen = [v for v in rows if _before(v.get('date'), B)]
    if not seen: B.excluded += 1; return None
    cur = seen[-1]; ver = str(cur.get('version') or '')
    it = {'id': 'doi:' + doi, 'doi': doi, 'server': RXIV_SERVER[server], 'title': cur.get('title'), 'year': first['date'][:4], 'date': first['date'][:10],
          'date_version': (cur.get('date') or '')[:10], 'version': ver, 'journal': RXIV_SERVER[server], 'first_author': (cur.get('authors') or '').split(';')[0].strip() or None,
          'category': cur.get('category'), 'license': cur.get('license'), 'type': 'preprint', 'peer_review': 'not peer reviewed (preprint)',
          'later_versions_masked': len(seen) < len(rows), 'published_doi': None, '_pub': pub,
          'url': f'https://www.{server}.org/content/{doi}v{ver}'}
    if with_abstract: it['abstract'] = ' '.join(str(cur.get('abstract') or '(no abstract available)').split())[:6000]
    return it


def rxiv_published(items, B):
    """The published-article link is shown only when Crossref attests its deposit AND publication < T (crossref_batch, strict); otherwise
    nothing is said about it (a publication on/after T is post-T knowledge). Not counted as an exclusion: the preprint itself stays."""
    pubs = [x['_pub'] for x in items if x.get('_pub')]; k = B.excluded
    try: ok = {c['id'][4:].lower(): c for c in crossref_batch(pubs, B)} if pubs else {}
    except Exception: ok = {}                                            # Crossref unreachable: link not attested -> not shown
    B.excluded = k
    for x in items:
        c = ok.get((x.pop('_pub', None) or '').lower())
        if c: x.update(published_doi=c['id'][4:], published_journal=c.get('journal'), published_year=c.get('year'))
    return items


def search_rxiv(server, q, n, B):
    qq = f'({q}) AND SRC:PPR AND PUBLISHER:"{RXIV_SERVER[server]}" AND FIRST_PDATE:[{B.start} TO {B.eve}] AND FIRST_IDATE:[{B.start} TO {B.eve}]'
    r = jget(EPMC + 'search?format=json&resultType=lite&pageSize=' + str(n) + '&query=' + urllib.parse.quote(qq))
    out, seen, undated, down = [], set(), 0, None
    for h in r.get('resultList', {}).get('result', []):
        doi = re.sub(r'v\d+$', '', (h.get('doi') or '').strip().lower())
        if doi in seen: continue
        seen.add(doi)
        if not re.fullmatch(RXIV_DOI, doi): B.excluded += 1; continue  # no openRxiv DOI: cannot be dated on the server -> refused
        if down: undated += 1; continue
        try: rows = rxiv_versions(server, doi)
        except Exception as e: down = str(e)[:80]; undated += 1; continue   # first failure stops the host for this call (no retry storm)
        x = rxiv_item(server, doi, rows, B, epmc=h)
        if x: out.append(x)
        elif not rows: B.excluded += 1
    if down and not out: raise ProviderError(f'provider_error: api.biorxiv.org unavailable ({down}); {undated} hits not datable (not an empty result)')
    return rxiv_published(out, B), (r.get('hitCount') if not undated else f"{r.get('hitCount')} in Europe PMC; {undated} hits not datable (api.biorxiv.org: {down})")


def search_biorxiv(q, n, B):
    """bioRxiv preprints: Europe PMC words (SRC:PPR, PUBLISHER bioRxiv, v1 posted and indexed <= eve of T), each hit dated on api.biorxiv.org."""
    return search_rxiv('biorxiv', q, n, B)


def search_medrxiv(q, n, B):
    """medRxiv preprints: same route as search_biorxiv (PUBLISHER medRxiv)."""
    return search_rxiv('medrxiv', q, n, B)


def rxiv_ident(ident):
    """'biorxiv:<doi>' | 'medrxiv:<doi>' -> (server, doi); 'doi:<openRxiv preprint DOI>' or the bare DOI -> (None, doi); else None."""
    p, _, v = ident.strip().partition(':'); p = p.lower()
    if p in RXIV_SERVER: return p, v.strip()
    d = re.sub(r'v\d+$', '', (v if p == 'doi' else ident).strip().replace('https://doi.org/', '').lower())
    return (None, d) if re.fullmatch(RXIV_DOI, d) else None


def rxiv_lookup(server, doi):
    """-> (server, rows); an unnamed server: medRxiv first for an 8-digit suffix, else bioRxiv, then the other one."""
    for s in [server] if server else (['medrxiv', 'biorxiv'] if len(doi.rsplit('.', 1)[-1]) == 8 else ['biorxiv', 'medrxiv']):
        rows = rxiv_versions(s, doi)
        if rows: return s, rows
    return server, []


def read_rxiv(server, doi, B, published=True):
    """Notice and abstract of the latest version posted before T (v1 < T required)."""
    doi = re.sub(r'v\d+$', '', doi.strip().replace('https://doi.org/', '').lower())
    if not re.fullmatch(RXIV_DOI, doi): return {'refusal': 'expected form biorxiv:<DOI> | medrxiv:<DOI>, e.g. biorxiv:10.1101/2020.03.22.002386'}
    s, rows = rxiv_lookup(server, doi)
    if not rows: return {'refusal': 'not found on api.biorxiv.org'}
    it = rxiv_item(s, doi, rows, B, with_abstract=True)
    if not it: return {'refusal': 'after T or forbidden'}
    return rxiv_published([it], B)[0] if published else it


def rxiv_match(ident): return rxiv_ident(ident) is not None


def read_rxiv_ident(ident, B):
    r = rxiv_ident(ident)
    return read_rxiv(r[0], r[1], B)


def _posted(ident, B):
    """(server, doi) of a preprint whose v1 is before T, else None."""
    r = rxiv_ident(ident)
    return None if 'refusal' in read_rxiv(r[0], r[1], B, published=False) else r


def citing_rxiv(ident, n, B):
    r = _posted(ident, B)
    return ([], 'document after T, forbidden or not found') if r is None else citing_doi('doi:' + r[1], n, B)


def references_rxiv(ident, n, B):
    r = _posted(ident, B)
    return ([], 'document after T, forbidden or not found') if r is None else references_doi('doi:' + r[1], n, B)


def related_rxiv(ident, n, B):
    r = _posted(ident, B)
    return ([], 'document after T, forbidden or not found') if r is None else related_work(oa_work('doi:' + r[1]), n, B)


SOURCE = {
    'name': 'biorxiv', 'order': 150,
    'engines': {'biorxiv': search_biorxiv, 'medrxiv': search_medrxiv},
    'ids': [{'prefix': 'biorxiv', 'form': r'10\.\S+'}, {'prefix': 'medrxiv', 'form': r'10\.\S+'}],
    'match': rxiv_match, 'read': read_rxiv_ident, 'citing': citing_rxiv, 'references': references_rxiv, 'related': related_rxiv,
    'plugins': ('biology',), 'access': 'api',
    'hosts': {'api.biorxiv.org': {'interval': 1.0, 'stop': (403, 429)}},       # no published limit: 1 req/s, stop on 403/429
    'terms': 'api.biorxiv.org (openRxiv), keyless; bioRxiv FAQ: free and unrestricted access, including machine analysis; www.biorxiv.org never called',
    'barrier': 'provider side (Europe PMC): FIRST_PDATE and FIRST_IDATE <= eve of T; local: v1 posted < T, metadata and abstract of the latest '
               'version posted < T; the published version only when dated < T',
}
