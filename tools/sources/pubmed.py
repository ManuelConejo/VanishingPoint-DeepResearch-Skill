# SPDX-License-Identifier: Apache-2.0
"""PubMed (NCBI E-utilities): search-pubmed, read pmid:<n> (also a bare number). Optional NCBI_API_KEY (10 req/s instead of 3)."""
import urllib.error, urllib.parse, urllib.request
from sources._common import jget, live_key
import code_sources as sc
from sources._common import STATE, fetch


def ncbi_key():
    """NCBI_API_KEY as an E-utilities `api_key=` parameter (10 req/s instead of 3); '' without a key."""
    k = live_key('NCBI_API_KEY')
    return '&api_key=' + urllib.parse.quote(k) if k else ''


# ---------------------------------------------------------------- engines

def pubmed_summ(ids, B):
    if not ids: return []
    s = jget('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id=' + ','.join(ids) + ncbi_key())['result']
    out = []
    for i in ids:
        r = s.get(i, {})
        doi = next((a['value'] for a in r.get('articleids', []) if a.get('idtype') == 'doi'), None)
        hist = {h['pubstatus']: h['date'] for h in r.get('history', [])}
        dates = [hist.get('entrez'), r.get('epubdate') or r.get('sortpubdate')]
        if not B.ok(doi, *dates, title=r.get('title')): continue
        out.append({'id': f'pmid:{i}', 'doi': doi, 'title': r.get('title'), 'year': (r.get('pubdate') or '')[:4],
                    'journal': r.get('source'), 'first_author': (r.get('authors') or [{}])[0].get('name')})
    return out


def search_pubmed(q, n, B):
    url = (f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmode=json&sort=relevance&datetype=edat&mindate={B.start:%Y/%m/%d}'
           f'&maxdate={B.eve:%Y/%m/%d}&retmax={n}&term=' + urllib.parse.quote(q) + ncbi_key())
    r = jget(url)['esearchresult']
    return pubmed_summ(r.get('idlist', []), B), int(r.get('count', 0))


def read_pubmed(ident, B):
    """pmid:<n> or a bare number: the PubMed summary (dated < T) and its abstract (efetch, text)."""
    pmid = ident.split(':')[-1]
    meta = pubmed_summ([pmid], B)
    if not meta: return {'refusal': 'after T, forbidden or not found'}
    x = fetch(f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&rettype=abstract&retmode=text' + ncbi_key()).decode('utf-8', 'replace')
    return dict(meta[0], abstract=x[:6000])


def bare_pmid(ident): return ident.isdigit()


def check_key(state):
    """Live check of NCBI_API_KEY (setup_keys.py): one minimal esearch through fetch (a rejected key is retried without it and named)."""
    jget('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmode=json&retmax=1&term=test' + ncbi_key())
    return 'refused' if 'NCBI_API_KEY' in sc.invalid_keys(STATE) else 'ok'


SOURCE = {
    'name': 'pubmed', 'order': 40,
    'engines': {'pubmed': search_pubmed},
    'ids': [{'prefix': 'pmid', 'form': r'\d+', 'export': 'article', 'export_rank': 110}],
    'match': bare_pmid, 'read': read_pubmed,
    'plugins': ('biology',), 'access': 'api',
    'hosts': {'eutils.ncbi.nlm.nih.gov': {'interval': 0.45}},
    'terms': 'NCBI E-utilities usage guidelines: 3 requests/s without a key, 10 with NCBI_API_KEY',
    'barrier': 'provider side: datetype=edat, mindate/maxdate = [start, eve of T]; local: Entrez date AND electronic (or sort) publication date < T, '
               'forbidden DOIs and titles (B.ok)',
    'key': {'vars': ('NCBI_API_KEY',), 'send': 'query:api_key', 'hosts': ('eutils.ncbi.nlm.nih.gov',), 'without': 'degraded',
            'reason': '3 req/s instead of 10', 'free': 'free, NCBI account', 'url': 'https://ncbiinsights.ncbi.nlm.nih.gov/2017/11/02/new-api-keys-for-the-e-utilities/',
            'suggest': ('PubMed with an NCBI key', '~5 min', True), 'labels': ['PubMed (NCBI)'], 'check': check_key,
            'rejected': {'codes': (400,), 'markers': (b'api key invalid', b'api key not wellformed')},   # NCBI: 400, or "not wellformed" for a mistyped key (2026-10-28)
            'interval_with_key': {'eutils.ncbi.nlm.nih.gov': 0.11}},
}
