# SPDX-License-Identifier: Apache-2.0
"""French administrative courts open data (opendata.justice-administrative.fr, JSON back end of the public engine, level 2 `page`):
search-justice-administrative [--court] [--from] [--to], read ja:<court>/<file>; FR ECLI read helper."""
import datetime as dt
import re
import urllib.error, urllib.parse, urllib.request
from sources._common import jget, law_ok
from sources._common import LAW_NO_CHAIN, RELATED_ONLY, value


JA = 'https://opendata.justice-administrative.fr/recherche/api/'
JA_COVERAGE = {'CE': '2021-09-30', 'CAA': '2022-03-31', 'TA': '2022-06-30'}   # law.md 4: opening of the open data per court level
JA_NULL = ('', 'undefined', 'null', 'none')


def ja_cov(code): return next((v for k, v in JA_COVERAGE.items() if (code or '').startswith(k)), None)


def ja_item(h, B):
    s = h.get('_source') or {}
    code, ident = s.get('Code_Juridiction') or '', (s.get('Identification') or '').removesuffix('.xml')
    ecli = None if str(s.get('Numero_ECLI') or '').strip().lower() in JA_NULL else s['Numero_ECLI']   # literal "undefined" removed
    if not code or not ident: return None
    # decision date AND upload date to the open data (lastModified) < T
    if not law_ok(B, [ecli, s.get('Numero_Dossier'), f'ja:{code}/{ident}'], [s.get('Date_Lecture'), s.get('lastModified')]): return None
    return {'id': f'ja:{code}/{ident}', 'ecli': ecli, 'doi': None, 'number': s.get('Numero_Dossier'),
            'title': f"{s.get('Nom_Juridiction')}, {s.get('Type_Decision') or 'decision'} n° {s.get('Numero_Dossier')}, {s.get('Date_Lecture')}",
            'year': (s.get('Date_Lecture') or '')[:4], 'date': s.get('Date_Lecture'), 'date_published': s.get('lastModified'),
            'journal': 'opendata.justice-administrative.fr', 'court': code, 'court_name': s.get('Nom_Juridiction'), 'formation': s.get('Formation_Jugement'),
            'publication': s.get('Code_Publication') or None, 'type': 'decision', 'tier': 'primary', 'order': 'FR-ADM', 'coverage_from': ja_cov(code)}


def _ja_hits(r): return ((r.get('decisions') or {}).get('body') or {}).get('hits') or {}


JA_COURT = r'CE|CAA\d{2}|TA\d{2,3}'   # exact court code (probe 2026-10-28: "TA" or "CAA" alone match nothing)


def search_justice_administrative(q, n, B, court=None, date_from=None, date_to=None):
    """Administrative courts open data (level 2 `page`): JSON back end of the public engine, decision date bounded on the provider side
    (model_searchANDdates, Date_Lecture range ending on the eve of T); several words = OR, exact phrase in quotes, numbers work.
    The provider has no relevance order (no score; probe 2026-10-28): results come sorted by date, most recent first. To narrow:
    court (exact code, model_search_date_juri route), date_from / date_to (decision-date window, kept inside [start, eve of T])."""
    qq = ' '.join(q.replace('/', ' ').split())
    if not qq: return [], 'empty query'
    if court and not re.fullmatch(JA_COURT, court): return [], f'court: exact code expected ({JA_COURT}, e.g. CE, TA75, CAA69)'
    lo, hi = B.start, B.eve
    for v, side in ((date_from, 'from'), (date_to, 'to')):
        if v is None: continue
        try: d = dt.date.fromisoformat(v)
        except (TypeError, ValueError): return [], f'{side}: date YYYY-MM-DD expected'
        if side == 'from': lo = max(lo, d)
        else: hi = min(hi, d)
    if lo > hi: return [], f'empty window ({lo} > {hi}; the end is at most the eve of T)'
    route = f'model_search_date_juri/openData/Date_Lecture/{urllib.parse.quote(qq, safe="")}/{court}' if court else f'model_searchANDdates/openData/Date_Lecture/{urllib.parse.quote(qq, safe="")}'
    h = _ja_hits(jget(f'{JA}{route}/{lo}/{hi}/100'))
    out = [x for x in (ja_item(i, B) for i in h.get('hits') or []) if x]
    tot = (h.get('total') or {}).get('value') if isinstance(h.get('total'), dict) else h.get('total')
    cov = ', '.join(f'{k} {v}' for k, v in JA_COVERAGE.items())
    return out[:n], (f'bounded: provider announces {tot} (false totals, capped at 1,000, 100 per call); sorted by date, most recent first (no relevance order): '
                     f'search a known decision by its number or an exact phrase in quotes, or narrow with --court / --from / --to; window {lo} to {hi}'
                     f'{", court " + court if court else ""}; coverage_from {cov}')


def read_ja(ident, B):
    m = re.fullmatch(r'([A-Z]{2,3}\d{0,3})/([A-Z]{2,5}_[A-Za-z0-9]+_\d{8})', ident)
    if not m: return {'refusal': 'expected form ja:<court code>/<file>, e.g. ja:CE/DCE_515092_20261027'}
    hits = _ja_hits(jget(f'{JA}elastic/decisions/{m.group(1)}/{m.group(2)}')).get('hits') or []
    hit = next((x for x in hits if (x.get('_source') or {}).get('Identification', '').removesuffix('.xml') == m.group(2)), None)
    if not hit: return {'refusal': 'not found'}
    it = ja_item(hit, B)
    if not it: return {'refusal': 'after T or forbidden'}
    return dict(it, abstract=str(hit['_source'].get('paragraph') or '(no text available)').replace('$$$', '\n')[:20000])


def read_ecli_fr(ecli, B):
    m = re.fullmatch(r'ECLI:FR:[A-Z]+:\d{4}:([0-9A-Z]+)\.\d{8}', ecli)
    if not m: return {'refusal': 'not an administrative-court ECLI (judicial ECLI: search-judilibre by the appeal number, then read judilibre:<id>)'}
    hits = _ja_hits(jget(f'{JA}Simple_Search/openData/{urllib.parse.quote(m.group(1))}/100')).get('hits') or []
    hit = next((x for x in hits if (x.get('_source') or {}).get('Numero_ECLI') == ecli), None)
    if not hit: return {'refusal': 'not found'}
    return read_ja(f"{hit['_source']['Code_Juridiction']}/{hit['_source']['Identification'].removesuffix('.xml')}", B)


def read_ja_ident(ident, B): return read_ja(value(ident), B)


SOURCE = {
    'name': 'justice-administrative', 'order': 60,
    'engines': {'justice-administrative': {'search': search_justice_administrative, 'options': ('court', 'date_from', 'date_to')}},
    'ids': [{'prefix': 'ja', 'form': r'[A-Z]{2,3}\d{0,3}/[A-Z]{2,5}_[A-Za-z0-9]+_\d{8}', 'law_form': r'[A-Z]{2,3}\d{0,3}/[A-Z]{2,5}_[A-Za-z0-9]+_\d{8}', 'export': 'case', 'export_rank': 50}],
    'read': read_ja_ident, 'citing': LAW_NO_CHAIN, 'references': LAW_NO_CHAIN, 'related': RELATED_ONLY,
    'plugins': ('law',), 'access': 'page',
    'hosts': {'opendata.justice-administrative.fr': {'interval': 3.0, 'stop': (403, 429)}},   # level 2: stop at once on 403/429
    'terms': 'open data of the French administrative courts; undocumented endpoint of the public search -> ACCESS-POLICY level 2 (page cadence)',
    'barrier': 'provider side: decision date range ending on the eve of T; local: decision date AND open data upload date (lastModified) < T; '
               'coverage start per court level reported (JA_COVERAGE)',
}
