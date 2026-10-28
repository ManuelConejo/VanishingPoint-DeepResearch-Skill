# SPDX-License-Identifier: Apache-2.0
"""DOI (default source): reads doi:10.x, bare DOIs and every identifier no other source claims; citation chaining (citing,
references, related) of doi:, pmid: and arXiv ids. Europe PMC, OpenCitations, Crossref and OpenAlex, each record dated < T."""
import re
import urllib.error, urllib.parse, urllib.request
from sources._common import _mailto, jget, year_before_T
from sources.arxiv import _arxiv_ok
from sources.crossref import cr_item, crossref_batch, crossref_deposit
from sources.datacite import datacite_read
from sources.europepmc import EPMC, epmc_date, epmc_item, epmc_resolve
from sources.openalex import _references_openalex, oa_item, oa_work, search_openalex
from sources.opencitations import complement, oc_citing, oc_references


def read_doi(ident, B):
    """A DOI (doi:10.x or bare), or any identifier no other source claims (OpenAlex W id): Europe PMC core abstract, else OpenAlex
    (abstract rebuilt, Crossref deposit AND publication < T), else Crossref."""
    ident = ident.strip()
    doi = ident[4:] if ident.lower().startswith('doi:') else ident
    r = jget('https://www.ebi.ac.uk/europepmc/webservices/rest/search?format=json&resultType=core&pageSize=1&query=' + urllib.parse.quote(f'DOI:"{doi}"'))
    res = r.get('resultList', {}).get('result', [])
    if res and res[0].get('abstractText'):
        it = epmc_item(res[0], B)
        if not it: return {'refusal': 'after T or forbidden'}
        return dict(it, abstract=re.sub('<[^>]+>', ' ', res[0]['abstractText'])[:6000])
    try: w = oa_work('doi:' + doi)
    except Exception:
        try: m = jget('https://api.crossref.org/works/' + urllib.parse.quote(doi) + _mailto('?'))['message']
        except Exception: return _datacite_or(doi, B, {'refusal': 'not found'})
        it = cr_item(m, B)
        if not it: return {'refusal': 'after T, forbidden or not found'}
        return dict(it, abstract=re.sub('<[^>]+>', ' ', m.get('abstract') or '(no abstract available)')[:6000])
    it = oa_item(w, B)
    if not it: return {'refusal': 'after T, forbidden or deposit not attested'}
    if not crossref_deposit([it], B): return _datacite_or(doi, B, {'refusal': 'after T, forbidden or deposit not attested'})
    inv = w.get('abstract_inverted_index') or {}
    pos = sorted((p, word) for word, ps in inv.items() for p in ps)
    return dict(it, abstract=' '.join(m for _, m in pos)[:6000] or '(no abstract available)')


def _datacite_or(doi, B, refusal):
    """A DOI Crossref does not attest may be a DataCite DOI (dataset, software, arXiv, Zenodo): its DataCite record under the same barrier
    (issued, created AND registered < T), else the original refusal."""
    try: r = datacite_read(doi, B)
    except Exception: r = None
    return r if r else refusal


def doi_of(ident, B):
    if ident.lower().startswith('doi:'): return ident[4:]
    r = epmc_resolve(ident, B)
    if r:
        res = jget(EPMC + 'search?format=json&resultType=lite&pageSize=1&query=' + urllib.parse.quote(f'EXT_ID:{r[1]} AND SRC:{r[0]}')).get('resultList', {}).get('result', [])
        return (res[0].get('doi') if res else None)
    return None


def citing_doi(ident, n, B):
    """Citing works of doi:, pmid:, arxiv: (and of every identifier handed to the default source): Europe PMC, then OpenCitations with a
    Crossref recheck, then OpenAlex cites: (each citing work dated < T)."""
    if ident.lower().startswith('arxiv:'):
        if not _arxiv_ok(ident, B): return [], 'document after T or forbidden'
        w = oa_work(ident)
        return search_openalex('', n, B, ',cites:' + w['id'].rsplit('/', 1)[-1])
    r = epmc_resolve(ident, B)
    if r and r[2]:
        cit = jget(EPMC + f'{r[0]}/{r[1]}/citations?format=json&pageSize=1000').get('citationList', {}).get('citation', [])
        ids = [c['id'] for c in cit if c.get('source') == 'MED' and str(c.get('pubYear') or '9999') <= str(B.T.year)]
        B.excluded += len(cit) - len(ids)
        out = epmc_date(ids, B)
        if out or cit:
            more = complement(out[:n], n, oc_citing, _given_doi(ident), B)   # OpenCitations works not in Europe PMC, after them
            return more, f'{len(cit)} citing in Europe PMC (all dates), {len(out)} before T' + _oc_note(more, out[:n])
    if r and not r[2]: return [], 'document after T or forbidden'
    doi = doi_of(ident, B)
    if doi:
        if not crossref_batch([doi], B): return [], 'document after T, forbidden or deposit not attested'
        try:
            cit = jget('https://api.opencitations.net/index/v2/citations/doi:' + doi)
            dois = [t[4:] for c in cit if str(c.get('creation') or '9999') < str(B.T) for t in c.get('citing', '').split() if t.startswith('doi:')]
            B.excluded += len(cit) - len(dois)
            out = crossref_batch(dois, B)
            if out or cit: return out[:n], f'{len(cit)} citing in OpenCitations (all dates), {len(out)} before T (Crossref recheck)'
        except Exception: pass
    w = oa_work(ident)
    return search_openalex('', n, B, ',cites:' + w['id'].rsplit('/', 1)[-1])


def references_doi(ident, n, B):
    """References of doi:, pmid:, arxiv:: Europe PMC, then Crossref, then OpenAlex; a reference without identifier is kept only when its
    year is strictly before the year of T."""
    if ident.lower().startswith('arxiv:'):
        if not _arxiv_ok(ident, B): return [], 'document after T or forbidden'
        return _references_openalex(oa_work(ident), n, B)
    r = epmc_resolve(ident, B)
    if r and not r[2]: return [], 'document after T or forbidden'
    if r:
        refs = jget(EPMC + f'{r[0]}/{r[1]}/references?format=json&pageSize=1000').get('referenceList', {}).get('reference', [])
        med = [x['id'] for x in refs if x.get('source') == 'MED' and x.get('id')]
        out = epmc_date(med, B) if med else []
        for x in refs:
            if x.get('source') == 'MED' and x.get('id'): continue
            # without PMID: year strictly before the year of T (strict), forbidden titles filtered
            if not B.ok(x.get('doi'), year_before_T(x.get('pubYear'), B), title=x.get('title')): continue
            out.append({'id': f"doi:{x['doi']}" if x.get('doi') else 'no-id', 'title': x.get('title'), 'year': x.get('pubYear'), 'journal': x.get('journalAbbreviation'), 'first_author': (x.get('authorString') or '').split(',')[0]})
        if out: return _oc_total(complement(out, n, oc_references, _given_doi(ident), B), out, len(refs))
    doi = doi_of(ident, B)
    if doi:
        try: m = jget('https://api.crossref.org/works/' + urllib.parse.quote(doi) + _mailto('?'))['message']
        except Exception: m = None
        if m is not None:
            if not cr_item(m, B): return [], 'document after T, forbidden or deposit not attested'
            refs = m.get('reference', [])
            out = crossref_batch([x['DOI'] for x in refs if x.get('DOI')], B)
            for x in refs:
                if x.get('DOI'): continue
                t = x.get('article-title') or x.get('unstructured') or x.get('volume-title')
                if t and B.ok(None, year_before_T(x.get('year'), B), title=t):
                    out.append({'id': 'no-id', 'title': t[:300], 'year': x.get('year'), 'first_author': x.get('author')})
            if out: return _oc_total(complement(out, n, oc_references, doi, B), out, len(refs))
    w = oa_work(ident)
    if not oa_item(w, B): return [], 0
    out, tot = _references_openalex(w, n, B)
    return _oc_total(complement(out, n, oc_references, doi, B), out, tot)


# ---- OpenCitations complement (sources/opencitations.py): existing items unchanged and first; the total keeps its form when nothing is added

def _given_doi(ident):
    return ident.strip()[4:] if ident.strip().lower().startswith('doi:') else None


def _oc_note(more, out):
    return f'; +{len(more) - len(out)} from OpenCitations (Crossref recheck)' if len(more) > len(out) else ''


def _oc_total(more, out, total):
    return (more, total) if len(more) == len(out) else (more, f'{total} (+{len(more) - len(out)} from OpenCitations, Crossref recheck)')


# ---- related works (OpenAlex related_works of a work; same barrier as citing/references)

def related_doi(ident, n, B):
    """OpenAlex related_works of a work dated < T (arXiv: v1 < T; other: OpenAlex publication date < T); each related work rechecked like an
    OpenAlex search result (publication < T, then Crossref deposit AND publication < T; no Crossref DOI -> refused)."""
    s = ident.strip().lower()
    if s.startswith('arxiv:'):
        if not _arxiv_ok(ident, B): return [], 'document after T or forbidden'
    w = oa_work(ident.strip())
    if not s.startswith('arxiv:') and not oa_item(w, B): return [], 'document after T or forbidden'
    return related_work(w, n, B)


def related_work(w, n, B):
    """Related works of an OpenAlex work already checked against the barrier."""
    out, tot = _references_openalex({'referenced_works': w.get('related_works') or []}, n, B)
    return out[:n], f'{tot} related works in OpenAlex (all dates), {len(out)} before T (Crossref recheck)'


SOURCE = {
    'name': 'doi', 'order': 20, 'default': True,
    'ids': [{'prefix': 'doi', 'form': r'10\.\S+', 'export': 'article', 'export_rank': 110}],
    'read': read_doi, 'citing': citing_doi, 'references': references_doi, 'related': related_doi,
    'plugins': ('biology', 'cs-ai', 'finance', 'law'), 'access': 'api',
    'hosts': {'api.opencitations.net': {'interval': 0.4}},
    'terms': 'OpenCitations COCI (CC0 data); Europe PMC, OpenAlex and Crossref: see their own declarations',
    'barrier': 'read: Europe PMC first index and publication dates < T, or OpenAlex publication < T plus Crossref deposit AND publication < T, '
               'or Crossref issued AND created < T; citing: every citing work rechecked (Europe PMC dates, Crossref deposit); a reference without '
               'identifier only when its year is strictly before the year of T',
}
