# SPDX-License-Identifier: Apache-2.0
"""HUDOC RSS search feed, case law of the European Court of Human Rights (level 2 `page`): search-hudoc-feed.

The feed is a published HUDOC feature: the Court's HUDOC manual (Annex 7) says "Click on the RSS button to create an RSS feed for the
criteria used in your search", and the feed is meant for feed readers, i.e. automated clients. The engine builds the same feed URL as
that button, with the same declarative user agent as every source, and stops at once on a challenge (403) or a rate limit (429): no
other client, no browser, no workaround. Records are identified `hudoc:<itemid>`, the identifier of the `hudoc` source, which reads them
(record and text) when the HUDOC back end answers. The feed gives no ECLI, respondent, conclusion or language: they are not served."""
import email.utils, re
import urllib.error, urllib.parse
import xml.etree.ElementTree as ET
from sources._common import LAW_NO_CHAIN, RELATED_ONLY, fetch, law_ok
from sources.hudoc import CHALLENGE, HUDOC, ITEMID, _query, _words

FEED = HUDOC + 'transform/rss?'
FEED_LIBRARY = 'echreng'          # the library of the English HUDOC interface; the language filter itself is in the query (ENG, FRE)
FEED_PAGE = 50                    # rows asked at most per feed request (same ceiling as the public front end)
FEED_OVERFETCH = 2                # rows asked per wanted result (rows refused locally are rare: the query is bounded to the eve of T)
KINDS = (('judgment', re.compile(r'\bjudg(?:e)?ment\b', re.I)), ('decision', re.compile(r'\bdecision\b', re.I)))


class FeedBlocked(Exception):
    """The feed answered with a challenge (403) or a rate limit (429): a receipt, never "nothing found", never a workaround."""


def _blocked(code):
    return {'status': 'blocked', 'reason': 'bot_challenge', 'refusal': f'bot_challenge: the HUDOC RSS feed answered HTTP {code} (challenge or '
            'rate limit); stopped for this host, no workaround (ACCESS-POLICY level 3); ECHR coverage not observable in this run'}


def feed_url(query, n):
    return FEED + urllib.parse.urlencode({'library': FEED_LIBRARY, 'query': query, 'sort': 'kpdate Descending', 'start': 0, 'length': n},
                                         quote_via=urllib.parse.quote)


def _date(s):
    """RFC 822 pubDate of the feed (the decision date, kpdate, at 00:00 GMT) -> ISO date, or None (refused downstream)."""
    try: d = email.utils.parsedate_to_datetime((s or '').strip())
    except (TypeError, ValueError, IndexError): return None
    return d.date().isoformat() if d else None


def parse_feed(data):
    """RSS 2.0 bytes -> list of {itemid, title, date, appno, label}. A document declaring a DTD or entities is refused whole (no entity is
    ever expanded); a body that is not RSS (an HTML challenge page served with 200) raises ValueError."""
    u = data.upper()
    if b'<!DOCTYPE' in u or b'<!ENTITY' in u: raise ValueError('feed declares a DTD or entities: refused')
    root = ET.fromstring(data)
    if root.tag != 'rss': raise ValueError('not an RSS document')
    out = []
    for it in root.iter('item'):
        g = (it.findtext('guid') or it.findtext('link') or '').strip()
        m = re.search(r'[?&]i=(' + ITEMID + r')(?:&|$)', g)
        m2 = re.fullmatch(r'\s*(.*?)\s+-\s*(.*?)\s*', it.findtext('description') or '', re.S)   # "<appno;appno> - <formation>"
        appno, label = (m2.group(1), m2.group(2)) if m2 else ('', (it.findtext('description') or '').strip())
        out.append({'itemid': m.group(1) if m else None, 'title': (it.findtext('title') or '').strip() or None,
                    'date': _date(it.findtext('pubDate')), 'appno': appno.strip(), 'label': label.strip()})
    return out


def feed_item(r, B):
    """One feed row -> the item served, or None (barrier). Date: pubDate = decision date (kpdate) < T; no date -> refused. Only judgments
    and decisions, as in the query: a label naming another kind is refused; an empty label (measured on Grand Chamber decisions,
    2026-10-28) is kept as 'judgment or decision' (the query admits only those doctypes)."""
    iid, d = r.get('itemid'), r.get('date')
    if not iid or not re.fullmatch(ITEMID, iid): return None
    kind = next((k for k, rx in KINDS if rx.search(r.get('label') or '')), None if r.get('label') else 'judgment or decision (label not given by the feed)')
    if not kind: return None
    apps = [x.strip() for x in (r.get('appno') or '').split(';') if re.fullmatch(r'\d{1,6}/\d{2}', x.strip())]
    if not law_ok(B, [iid, 'hudoc:' + iid, *apps], [d], [r.get('title')]): return None
    return {'id': 'hudoc:' + iid, 'itemid': iid, 'ecli': None, 'doi': None, 'title': r.get('title'), 'year': d[:4], 'date': d,
            'application_numbers': apps, 'formation': r.get('label') or None, 'respondent': None, 'conclusion': None,
            'language': None, 'journal': 'HUDOC RSS feed (ECHR)', 'court': 'ECHR', 'type': 'decision', 'decision_kind': kind,
            'tier': 'primary', 'order': 'COE', 'set_aside_by': None,
            'validity': 'importance level, ECLI, respondent and conclusion not given by the feed (read hudoc:<itemid> for the record)'}


def search_hudoc_feed(q, n, B):
    """HUDOC RSS search feed: words of the question, each quoted and joined with AND; ECHR collection, official languages (ENG, FRE),
    judgments and decisions; decision date (kpdate) bounded in the query to [start, eve of T], most recent first; local recheck of the
    date (pubDate) under the barrier."""
    ws = _words(q)
    if not ws: return [], 'no usable word'
    url = feed_url(_query('(' + ' AND '.join(f'"{w}"' for w in ws) + ')', B), max(n, min(FEED_PAGE, FEED_OVERFETCH * n)))
    try: data = fetch(url)
    except urllib.error.HTTPError as e:
        if e.code in CHALLENGE: return _blocked(e.code), 'bot_challenge'
        raise
    try: rows = parse_feed(data)
    except (ValueError, ET.ParseError) as e:
        return {'status': 'blocked', 'reason': 'bot_challenge', 'refusal': f'the HUDOC RSS feed did not answer with RSS ({e}): no workaround'}, 'bot_challenge'
    out = [x for x in (feed_item(r, B) for r in rows) if x]
    return out[:n], (f'HUDOC RSS feed: {len(rows)} rows, total not given by the feed; sorted by decision date, most recent first '
                     f'(window {B.start} to {B.eve})')


SOURCE = {
    'name': 'hudoc-feed', 'order': 58,
    'engines': {'hudoc-feed': search_hudoc_feed},
    'ids': [],                                       # items carry hudoc:<itemid>, declared and read by the `hudoc` source
    'citing': LAW_NO_CHAIN, 'references': LAW_NO_CHAIN, 'related': RELATED_ONLY,
    'plugins': ('law',), 'access': 'page',
    'hosts': {'hudoc.echr.coe.int': {'interval': 3.0, 'timeout': 90, 'stop': (403, 404, 429)}},   # same host and pacing as `hudoc`
    'terms': 'ECHR "Copyright and disclaimer" (https://www.echr.coe.int/en/copyright-and-disclaimer): texts may be reproduced free of charge '
             'for private use or for information and education, source acknowledged; no clause on automated or AI use. RSS feed of a search: '
             'a feature documented in the HUDOC manual (Annex 7, "To create an RSS feed for the search criteria"); query syntax inside the '
             'feed URL not documented -> ACCESS-POLICY level 2 (page cadence, stop on 403/429, never a browser)',
    'barrier': 'provider side: kpdate (date of the judgment or decision) within [start, eve of T] in the feed query; local: pubDate (= kpdate) '
               '< T; no date -> refused; official languages only (in the query); importance level, ECLI, respondent and conclusion not served; '
               'HUDOC gives no upload date',
    'key': None,
}
