# SPDX-License-Identifier: Apache-2.0
"""SEC EDGAR (keyless; declared User-Agent with an e-mail contact required by the SEC): search-edgar "<words>" (full-text search of filings,
2001 onwards) or "cik:<CIK> [form:<form>]" (the filings of one company), read edgar:<CIK>/<accession number> (filing record and the start of
its primary document). Every filing dated (filing date AND acceptance time) before T. Without an e-mail address in VP_CONTACT: skipped,
not_configured, 0 request (the SEC answers 403 to undeclared tools)."""
import datetime as dt
import json
import os
import re
import urllib.error, urllib.parse
import code_sources as sc
from sources._common import CFG, ProviderError, extra_ok, fetch, plain, value, window
from sources._series import DataSkip, data_engine

EFTS = 'https://efts.sec.gov/LATEST/search-index'
SUBMISSIONS = 'https://data.sec.gov/submissions/'
ARCHIVES = 'https://www.sec.gov/Archives/edgar/data/'
LS = CFG['linked_sources']
INTERVAL = float(LS['sec_interval'])
ID_FORM = r'\d{1,10}/\d{10}-\d{2}-\d{6}'
EDGAR_NO_CHAIN = 'citation chaining not served for SEC filings (edgar:)'
FTS_FROM = '2001-01-01'                     # first day covered by EDGAR full-text search (SEC documentation)


def need_contact():
    """The declared User-Agent the SEC asks for (tool name and e-mail contact), built at call time from VP_CONTACT; no e-mail address in it
    -> not_configured skip before any request."""
    c = sc.contact()
    if not re.search(r'[^\s@]+@[^\s@]+\.[A-Za-z]{2,}', c):
        raise DataSkip('not_configured', 'the SEC requires a declared User-Agent with an e-mail contact: set VP_CONTACT to a team or project '
                                         'address (KEYS.md, "Identification contact"); 0 request')
    return {'User-Agent': 'VanishingPoint/1 (+' + c + ')'}


def sec_json(url): return json.loads(fetch(url, headers=need_contact()))


def cik10(c): return str(int(c)).zfill(10)


def filing_item(cik, adsh, form, filed, accepted, B, name=None, period=None, doc=None, desc=None):
    """One filing, or None (barrier): filing date AND acceptance time < T (no filing date -> refused); accession number and name checked
    against the forbidden lists."""
    if not (cik and adsh) or not extra_ok(B, [adsh, f'edgar:{int(cik)}/{adsh}'], [filed] + ([accepted] if accepted else []), [name]): return None
    url = ARCHIVES + f'{int(cik)}/{adsh.replace("-", "")}/' + (doc or f'{adsh}-index.htm')
    return {'id': f'edgar:{int(cik)}/{adsh}', 'title': ' '.join(x for x in (name, form, desc if desc and desc != form else None) if x),
            'company': name, 'cik': cik10(cik), 'form': form, 'date': filed, 'year': str(filed)[:4], 'period_of_report': period,
            'journal': 'SEC EDGAR', 'type': 'filing', 'url': url}


def _fts(words, forms, lo, hi, n):
    p = {'q': words, 'dateRange': 'custom', 'startdt': lo.isoformat(), 'enddt': hi.isoformat()}
    if forms: p['forms'] = forms
    r = sec_json(EFTS + '?' + urllib.parse.urlencode(p))
    if r.get('errorType'):                    # beyond 10,000 hits efts answers HTTP 200 with an error: bounded, never "nothing found"
        raise ProviderError(f"EDGAR full-text search: {r.get('errorType')} (bounded: narrow the words, the form or the window)")
    hits = (r.get('hits') or {}).get('hits') or []
    return hits, ((r.get('hits') or {}).get('total') or {}).get('value')


def _submissions(cik):
    return sec_json(SUBMISSIONS + f'CIK{cik10(cik)}.json')


def _rows(block):
    """Columnar submissions block -> list of dicts."""
    keys = ('accessionNumber', 'filingDate', 'acceptanceDateTime', 'form', 'primaryDocument', 'primaryDocDescription', 'reportDate')
    cols = {k: block.get(k) or [] for k in keys}
    return [{k: (cols[k][i] if i < len(cols[k]) else None) for k in keys} for i in range(len(cols['accessionNumber']))]


def _company_filings(cik, B, until=None):
    """Rows of a company's filings: the recent block, then up to linked_sources.sec_submission_files older files that start before T."""
    s = _submissions(cik)
    rows = _rows((s.get('filings') or {}).get('recent') or {})
    for f in [f for f in (s.get('filings') or {}).get('files') or [] if str(f.get('filingFrom') or '9999') < B.T.isoformat()][:int(LS['sec_submission_files'])]:
        if until and any(r['accessionNumber'] == until for r in rows): break
        rows += _rows(sec_json(SUBMISSIONS + f['name']))
    return s, rows


@data_engine(True)
def search_edgar(q, n, B, date_from=None, date_to=None):
    need_contact()
    w, err = window(B, date_from, date_to)
    if err: return [], err
    lo, hi = w
    m = re.fullmatch(r'\s*cik:(\d{1,10})(?:\s+form:(\S+))?\s*', str(q or ''), re.I)
    if m:
        s, rows = _company_filings(m.group(1), B)
        out = []
        for r in rows:
            if m.group(2) and (r['form'] or '').upper() != m.group(2).upper(): continue
            if not r['filingDate'] or not (lo.isoformat() <= r['filingDate'] <= hi.isoformat()): continue
            it = filing_item(s.get('cik') or m.group(1), r['accessionNumber'], r['form'], r['filingDate'], r['acceptanceDateTime'], B,
                             name=s.get('name'), period=r['reportDate'], doc=r['primaryDocument'], desc=r['primaryDocDescription'])
            if it: out.append(it)
        out.sort(key=lambda x: x['date'], reverse=True)
        return out[:n], f'{len(out)} filings of CIK {cik10(m.group(1))} dated before T in the window (company name as now)'
    words = re.sub(r'\bform:(\S+)', '', str(q or '')).strip()
    forms = ','.join(re.findall(r'\bform:(\S+)', str(q or '')))
    if not words: return [], 'expected words, or cik:<CIK> [form:<form>]'
    lo = max(lo, dt.date.fromisoformat(FTS_FROM))
    hits, total = _fts(words, forms, lo, hi, n)
    out, seen = [], set()
    for h in hits:
        x = h.get('_source') or {}
        adsh = x.get('adsh') or str(h.get('_id') or '').split(':')[0]
        if adsh in seen: continue
        seen.add(adsh)
        cik = (x.get('ciks') or [None])[0]
        name = re.sub(r'(\s+\([A-Z0-9.\-]+(?:,\s*[A-Z0-9.\-]+)*\))?\s+\(CIK \d+\)$', '', ((x.get('display_names') or [''])[0] or '')).strip() or None   # 'Name  (TICKERS)  (CIK n)'
        doc = str(h.get('_id') or '').partition(':')[2] or None
        it = filing_item(cik, adsh, x.get('form') or x.get('file_type'), x.get('file_date'), None, B, name=name, period=x.get('period_ending'),
                         doc=doc, desc=x.get('file_description'))
        if it: out.append(it)
        if len(out) >= n: break
    return out, total


def read_edgar(ident, B):
    """edgar:<CIK>/<accession number> -> the filing record (form, dates, company) and the start of its primary document
    (linked_sources.sec_text_chars characters), or a refusal (after T, not found, form)."""
    try: need_contact()
    except DataSkip as e: return {'status': 'skipped', 'reason': e.reason, 'refusal': f'{e.reason}: {e.detail}'}
    v = value(ident)
    if not re.fullmatch(ID_FORM, v): return {'refusal': 'expected form edgar:<CIK>/<accession number>, e.g. edgar:320193/0000320193-19-000119'}
    cik, adsh = v.split('/')
    try: s, rows = _company_filings(cik, B, until=adsh)
    except urllib.error.HTTPError as e:
        if e.code == 404: return {'refusal': 'not found (CIK unknown to EDGAR)'}
        raise
    r = next((x for x in rows if x['accessionNumber'] == adsh), None)
    if not r: return {'refusal': 'not found among the filings of this CIK'}
    it = filing_item(s.get('cik') or cik, adsh, r['form'], r['filingDate'], r['acceptanceDateTime'], B, name=s.get('name'),
                     period=r['reportDate'], doc=r['primaryDocument'], desc=r['primaryDocDescription'])
    if not it: return {'refusal': 'after T or forbidden'}
    it['accepted'] = r['acceptanceDateTime']
    it['company_as_of'] = 'now (current EDGAR name; former names in the submissions file)'
    if r['primaryDocument']:
        raw = fetch(it['url'], headers=need_contact())
        text = plain(raw.decode('utf-8', 'replace'))
        n = int(LS['sec_text_chars'])
        it['abstract'] = text[:n] + (f' [... text cut at {n:,} of {len(text):,} characters ...]' if len(text) > n else '')
    else: it['abstract'] = '(no primary document listed)'
    return it


SOURCE = {
    'name': 'edgar', 'order': 205,
    'engines': {'edgar': {'search': search_edgar, 'options': ('date_from', 'date_to')}},
    'ids': [{'prefix': 'edgar', 'form': ID_FORM, 'export': 'report', 'export_rank': 70}],
    'read': read_edgar, 'citing': EDGAR_NO_CHAIN, 'references': EDGAR_NO_CHAIN, 'related': EDGAR_NO_CHAIN,
    'plugins': ('finance',), 'access': 'api',
    'hosts': {h: {'interval': INTERVAL, 'stop': (403, 404, 429)} for h in ('efts.sec.gov', 'data.sec.gov', 'www.sec.gov')},
    'terms': 'SEC EDGAR APIs and archives, keyless, US public records; SEC fair access: declared User-Agent with company and e-mail, '
             'at most 10 requests per second (sec.gov/developer, SEC Privacy and Security Policy)',
    'barrier': 'provider side: full-text search window [start, eve of T] (startdt/enddt); local: filing date AND acceptance time < T; '
               'the company name is the current one (flagged)',
}
