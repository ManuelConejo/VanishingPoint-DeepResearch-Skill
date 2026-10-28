# SPDX-License-Identifier: Apache-2.0
"""HUDOC, case law of the European Court of Human Rights (level 2 `page`: JSON back end of the public HUDOC search, not documented by
the Court): search-hudoc, read hudoc:<itemid>; ECHR ECLI read helper (ecli:ECLI:CE:ECHR:...)."""
import re
import urllib.error, urllib.parse
from sources._common import fetch, head_tail, jget, law_ok, plain, value
from sources._common import LAW_NO_CHAIN, RELATED_ONLY

HUDOC = 'https://hudoc.echr.coe.int/app/'
HUDOC_DOCTYPES = ('HEJUD', 'HFJUD', 'HEDEC', 'HFDEC')     # judgments and decisions, English and French (the Court's official languages)
HUDOC_LANGS = ('ENG', 'FRE')                              # official languages only: translations into other languages are added later
HUDOC_FIELDS = 'itemid,docname,appno,kpdate,doctype,importance,respondent,conclusion,ecli,languageisocode'   # an unknown field = HTTP 404
HUDOC_PAGE = 50                                           # rows asked per search (the public front end asks 50 at most)
HUDOC_OVERFETCH = 2                                       # rows asked per wanted result (kpdate-sorted rows refused locally are rare)
HUDOC_WORDS = 8                                           # query words kept (each one quoted, joined with AND)
ITEMID = r'\d{3}-\d{1,7}'
ECHR_ECLI = r'ECLI:CE:ECHR:\d{4}:\d{4}[A-Z]{3}\d{9}'
CHALLENGE = (403, 429)                                    # Cloudflare "Just a moment" challenge / rate limit: stop, never work around


class HudocBlocked(Exception):
    """HUDOC answered with a bot challenge (403) or a rate limit (429): a receipt, never "nothing found", never a workaround."""


def _blocked(e):
    return {'status': 'blocked', 'reason': 'bot_challenge', 'refusal': f'bot_challenge: HUDOC answered HTTP {e} (challenge or rate limit); '
            'stopped for this host, no workaround (ACCESS-POLICY level 3); ECHR coverage not observable in this run'}


OPERATIVE_ECHR = re.compile(r'(FOR THESE REASONS,?\s+THE COURT|PAR CES MOTIFS,?\s+LA COUR)', re.I)


def _words(q):
    """Free words of the question, stripped of every query operator character (no query injection into HUDOC's syntax)."""
    return [w for w in re.findall(r"[^\W_]+(?:['-][^\W_]+)*", q or '') if len(w) >= 2][:HUDOC_WORDS]


def _query(core, B):
    """HUDOC query: ECHR collection, official languages, judgments and decisions, decision date (kpdate) within [start, eve of T]."""
    lang = ' OR '.join(f'languageisocode:"{x}"' for x in HUDOC_LANGS)
    doct = ' OR '.join(f'doctype={x}' for x in HUDOC_DOCTYPES)
    return (f'contentsitename:ECHR AND ({lang}) AND ({doct}) AND {core} '
            f'AND (kpdate>="{B.start}T00:00:00.0Z") AND (kpdate<="{B.eve}T00:00:00.0Z")')


def _results(query, n, sort='kpdate Descending'):
    url = HUDOC + 'query/results?' + urllib.parse.urlencode({'query': query, 'select': HUDOC_FIELDS, 'sort': sort, 'start': 0, 'length': n},
                                                             quote_via=urllib.parse.quote)
    try: r = jget(url)
    except urllib.error.HTTPError as e:
        if e.code in CHALLENGE: raise HudocBlocked(e.code)
        raise
    return [x.get('columns') or {} for x in r.get('results') or []], r.get('resultcount')


def hudoc_item(c, B):
    """One HUDOC row -> the item served, or None (barrier). Date: kpdate (date of the judgment or decision) < T; no date -> refused.
    The importance level is revised after delivery (key cases are designated later): it is never served."""
    iid, d = c.get('itemid'), (c.get('kpdate') or '')[:10] or None
    if not iid or not re.fullmatch(ITEMID, iid): return None
    if c.get('languageisocode') not in HUDOC_LANGS or c.get('doctype') not in HUDOC_DOCTYPES: return None
    ecli = c.get('ecli') or None
    if not law_ok(B, [ecli, iid, 'hudoc:' + iid, c.get('appno')], [d], [c.get('docname')]): return None
    judgment = c['doctype'] in ('HEJUD', 'HFJUD')
    return {'id': 'hudoc:' + iid, 'itemid': iid, 'ecli': ecli, 'doi': None, 'title': c.get('docname'), 'year': d[:4], 'date': d,
            'application_numbers': [x for x in (c.get('appno') or '').split(';') if x], 'respondent': c.get('respondent') or None,
            'conclusion': c.get('conclusion') or None, 'language': c.get('languageisocode'), 'journal': 'HUDOC (ECHR)', 'court': 'ECHR',
            'type': 'decision', 'decision_kind': 'judgment' if judgment else 'decision', 'tier': 'primary', 'order': 'COE',
            'set_aside_by': None, 'validity': 'importance level masked (revised after delivery)'}


def search_hudoc(q, n, B):
    """HUDOC search (level 2 `page`): words of the question, each quoted, joined with AND; decision date (kpdate) bounded on the provider side
    to [start, eve of T], most recent first; local recheck of kpdate. Official languages (ENG, FRE), judgments and decisions only."""
    ws = _words(q)
    if not ws: return [], 'no usable word'
    try: rows, tot = _results(_query('(' + ' AND '.join(f'"{w}"' for w in ws) + ')', B), max(n, min(HUDOC_PAGE, HUDOC_OVERFETCH * n)))
    except HudocBlocked as e: return _blocked(e), 'bot_challenge'
    out = [x for x in (hudoc_item(c, B) for c in rows) if x]
    return out[:n], f'provider announces {tot}; sorted by decision date, most recent first (window {B.start} to {B.eve})'


def _body(iid):
    """Full text of a HUDOC document (HTML conversion used by the public front end) -> plain text, or None."""
    try: x = fetch(HUDOC + 'conversion/docx/html/body?' + urllib.parse.urlencode({'library': 'ECHR', 'id': iid}))
    except urllib.error.HTTPError as e:
        if e.code in CHALLENGE: raise HudocBlocked(e.code)
        return None
    t = plain(re.sub(r'(?is)<(head|script|style)\b.*?</\1>', ' ', x.decode('utf-8', 'replace')))
    return t or None


def read_itemid(iid, B):
    if not re.fullmatch(ITEMID, iid): return {'refusal': 'expected form hudoc:<itemid>, e.g. hudoc:001-229320'}
    rows, _ = _results(_query(f'(itemid:"{iid}")', B), 1, sort='')
    if not rows:
        return {'refusal': 'not found, or dated on/after T (the query is bounded to the eve of T)'}
    it = hudoc_item(rows[0], B)
    if not it: return {'refusal': 'after T, forbidden or undated'}
    t = _body(iid)
    if not t: return dict(it, abstract='(no text available from HUDOC)')
    m = None
    for m in OPERATIVE_ECHR.finditer(t): pass                                      # the last one: the operative part closes the judgment
    t, how = head_tail(t, m.start() if m else None)
    return dict(it, abstract=t, text_source=f'HUDOC (text of the Court, {how})')


def read_ecli_echr(ecli, B):
    if not re.fullmatch(ECHR_ECLI, ecli): return {'refusal': 'malformed ECHR ECLI (expected ECLI:CE:ECHR:2023:1205JUD003561419)'}
    try: rows, _ = _results(_query(f'(ecli:"{ecli}")', B), HUDOC_PAGE, sort='')
    except HudocBlocked as e: return _blocked(e)
    row = next((c for c in rows if c.get('ecli') == ecli and c.get('languageisocode') == 'ENG'), None) or next((c for c in rows if c.get('ecli') == ecli), None)
    if not row: return {'refusal': 'not found, or dated on/after T'}
    try: return read_itemid(row['itemid'], B)
    except HudocBlocked as e: return _blocked(e)


def read_hudoc(ident, B):
    try: return read_itemid(value(ident), B)
    except HudocBlocked as e: return _blocked(e)


SOURCE = {
    'name': 'hudoc', 'order': 57,
    'engines': {'hudoc': search_hudoc},
    'ids': [{'prefix': 'hudoc', 'form': ITEMID, 'law_form': ITEMID, 'export': 'case', 'export_rank': 50}],
    'read': read_hudoc, 'citing': LAW_NO_CHAIN, 'references': LAW_NO_CHAIN, 'related': RELATED_ONLY,
    'plugins': ('law',), 'access': 'page',
    'hosts': {'hudoc.echr.coe.int': {'interval': 3.0, 'timeout': 90, 'stop': (403, 404, 429)}},   # level 2; 404 = unknown field or document
    'terms': 'ECHR "Copyright and disclaimer" (https://www.echr.coe.int/en/copyright-and-disclaimer): texts may be reproduced free of charge '
             'for private use or for information and education, source acknowledged; no clause on automated or AI use; '
             'HUDOC JSON back end not documented by the Court -> ACCESS-POLICY level 2 (page cadence, stop on 403/429, never a browser)',
    'barrier': 'provider side: kpdate (date of the judgment or decision) within [start, eve of T]; local: kpdate < T; no date -> refused; '
               'official languages only (later translations excluded); importance level masked (revised after delivery); HUDOC gives no '
               'upload date',
    'key': None,
}
