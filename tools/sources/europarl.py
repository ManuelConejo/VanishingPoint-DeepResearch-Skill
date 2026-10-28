# SPDX-License-Identifier: Apache-2.0
"""European Parliament Open Data API v2 (documented, keyless, CC BY 4.0): search-europarl (adopted texts, full-text search),
read europarl:<document id> (adopted texts TA-..., plenary documents A-/B-/RC-..., other documents)."""
import json
import re
import urllib.error, urllib.parse
from sources._common import TEXT_HEAD, _before, fetch, law_ok, plain, value
from sources._common import LAW_NO_CHAIN, RELATED_ONLY

EP = 'https://data.europarl.europa.eu/'
EP_API = EP + 'api/v2/'
EP_FORMAT = 'application/ld+json'
EP_LANGS = ('en', 'fr')                    # search language, then the text languages tried in order
EP_EARLIEST = '1952-09-10'                 # first sitting of the Common Assembly: lower bound sent when the barrier has none
EP_PAGE = 50                               # provider maximum per call (limit50)
EP_TEXT_FORMATS = ('xml', 'html')          # manifestations read as text (PDF and DOCX are not parsed)
EP_ID = r'[A-Z][A-Z0-9]{0,9}(-[A-Z0-9]{1,10}){2,6}'   # TA-8-2018-0529, A-8-2016-0164, B-9-2021-0123, RC-B9-2021-0170
EP_ROUTES = (('TA-', 'adopted-texts'), ('A-', 'plenary-documents'), ('B-', 'plenary-documents'), ('RC-', 'plenary-documents'))


def _get(path, params):
    """GET on the API (JSON-LD). HTTP 404 -> None; other HTTP errors propagate (typed by the gateway envelope)."""
    try: return json.loads(fetch(EP_API + path + '?' + urllib.parse.urlencode(dict(params, format=EP_FORMAT))))
    except urllib.error.HTTPError as e:
        if e.code == 404: return None
        raise


def _manifestations(w):
    """[(language code, format, file path, issued)] of a work, from its expressions."""
    out = []
    for e in w.get('is_realized_by') or []:
        lang = (e.get('id') or '').rsplit('/', 1)[-1]
        for m in e.get('is_embodied_by') or []:
            out.append((lang, (m.get('id') or '').rsplit('/', 1)[-1], m.get('is_exemplified_by'), m.get('issued')))
    return out


def _title(w):
    t = w.get('title_dcterms') or {}
    if isinstance(t, dict):
        for lang in EP_LANGS:
            if t.get(lang): return ' '.join(str(t[lang]).split())
        return next((' '.join(str(v).split()) for v in t.values() if v), None)
    return ' '.join(str(t).split()) or None


def ep_item(w, B):
    """One work -> the item served, or None (barrier). Date: document_date (sitting / adoption date) < T; no date -> refused.
    Links that point forward in time (inverse_* relations: answers, later realisations) are post-T knowledge: never served."""
    did, d = w.get('identifier'), w.get('document_date')
    title = _title(w)
    if not did or not re.fullmatch(EP_ID, did): return None
    if not law_ok(B, [did, 'europarl:' + did, w.get('notation_publicRegister')], [d], [title]): return None
    files_before = sorted({f for _, f, _, issued in _manifestations(w) if _before((issued or '')[:10], B)})
    return {'id': 'europarl:' + did, 'europarl': did, 'doi': None, 'title': title, 'year': d[:4], 'date': d[:10],
            'reference': w.get('notation_publicRegister') or w.get('label'), 'work_type': (w.get('work_type') or '').rsplit('/', 1)[-1] or None,
            'parliamentary_term': (w.get('parliamentary_term') or '').rsplit('-', 1)[-1] or None, 'adopts': [x.rsplit('/', 1)[-1] for x in w.get('adopts') or []],
            'procedure': [x.rsplit('/', 1)[-1] for x in w.get('inverse_created_a_realization_of') or []],
            'journal': 'European Parliament (Open Data API)', 'type': 'text', 'tier': 'grey', 'order': 'EU',
            'files_before_T': files_before, 'url': EP + 'eli/dl/doc/' + did}


def search_europarl(q, n, B):
    """Adopted texts, full-text search (`text`, English), sitting date bounded on the provider side to [start, eve of T], best score
    first; local recheck of the document date."""
    qq = ' '.join(re.findall(r'[^\W_]+', q or ''))
    if not qq: return [], 'empty query'
    lo = max(str(B.start), EP_EARLIEST)
    r = _get('adopted-texts', {'text': qq, 'search-language': EP_LANGS[0], 'sitting-date': lo, 'sitting-date-end': str(B.eve),
                               'sort-by': 'search-score:desc', 'offset': 0, 'limit': min(EP_PAGE, max(n, 1))}) or {}
    out = [x for x in (ep_item(w, B) for w in r.get('data') or []) if x]
    return out[:n], f"provider announces {(r.get('meta') or {}).get('total')}; adopted texts, window {lo} to {B.eve}, best score first"


def _route(did):
    return next((r for p, r in EP_ROUTES if did.startswith(p)), 'documents')


def read_ep(did, B):
    if not re.fullmatch(EP_ID, did): return {'refusal': 'expected form europarl:<document id>, e.g. europarl:TA-8-2018-0529'}
    r = _get(_route(did) + '/' + urllib.parse.quote(did), {})
    w = next(iter((r or {}).get('data') or []), None)
    if not w: return {'refusal': 'not found'}
    it = ep_item(w, B)
    if not it: return {'refusal': 'after T, forbidden or undated'}
    files = _manifestations(w)
    for lang in EP_LANGS:
        for fmt in EP_TEXT_FORMATS:
            for lg, f, path, issued in files:
                if lg != lang or f != fmt or not path: continue
                if not _before((issued or '')[:10], B):
                    continue                                                   # a file issued on/after T is never read (it may carry later corrections)
                try: x = fetch(EP + path)
                except Exception: continue
                t = plain(re.sub(r'(?is)<(head|script|style)\b.*?</\1>', ' ', x.decode('utf-8', 'replace')))
                if t:
                    cut = len(t) > TEXT_HEAD
                    return dict(it, abstract=t[:TEXT_HEAD] + (f' [... text cut at {TEXT_HEAD:,} of {len(t):,} characters ...]' if cut else ''),
                                text_language=lang, text_source=f'European Parliament ({fmt} issued {issued[:10]}, {"start" if cut else "whole"})')
    return dict(it, abstract='(no text file issued before T in ' + '/'.join(EP_LANGS) + ' as ' + '/'.join(EP_TEXT_FORMATS) + ': text not served)')


def read_europarl(ident, B): return read_ep(value(ident), B)


SOURCE = {
    'name': 'europarl', 'order': 52,
    'engines': {'europarl': search_europarl},
    'ids': [{'prefix': 'europarl', 'form': EP_ID, 'law_form': EP_ID, 'export': 'legislation', 'export_rank': 75}],
    'read': read_europarl, 'citing': LAW_NO_CHAIN, 'references': LAW_NO_CHAIN, 'related': RELATED_ONLY,
    'plugins': ('law',), 'access': 'api',
    'hosts': {'data.europarl.europa.eu': {'interval': 2.0, 'timeout': 90, 'stop': (403, 429)},      # robots Crawl-delay 2; API: 500 requests / 5 min
              'redmapl3.europarl.europa.eu': {'interval': 2.0, 'stop': (403, 429)}},              # text files (redirect target of /distribution/)
    'terms': 'European Parliament Open Data API v2 (OpenAPI licence: CC BY 4.0; Bureau decision of 16 December 2024 on open data, '
             'OJ C/2025/341: re-use under CC BY 4.0); keyless; "Maximum number of requests 500 in 5min"; identify with a User-Agent',
    'barrier': 'provider side: sitting date within [start, eve of T]; local: document date < T; no date -> refused; text read only from a '
               'file issued before T (else not served); forward links (inverse_* relations) never served',
    'key': None,
}
