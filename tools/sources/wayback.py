"""Internet Archive Wayback Machine (keyless, documented API): the LAST capture of a web page strictly before T.
Engine search-wayback <url> (the capture found, no content); identifier wayback:<url> (read: the capture's raw content).
CDX server API: https://web.archive.org/cdx/search/cdx?url=<url>&to=<eve of T>&limit=-1&output=json&filter=statuscode:200 (the last row);
Memento (RFC 7089) raw playback: https://web.archive.org/web/<timestamp>id_/<url> (id_ = the archived bytes, no toolbar, no link rewriting).
A capture date is an UPPER bound of the existence of the content, never its publication date: the page may be much older.
Level 1 (API documented, ACCESS-POLICY.md, decision of the owner 2026-11-01). Standard library only."""
import datetime as dt
import json
import re
import time
import urllib.error, urllib.parse

from sources._common import EXTRA_NO_CHAIN, RELATED_ONLY, STATE, TEXT_HEAD, ProviderError, extra_ok, fetch, plain, value

HOST = 'web.archive.org'
CDX = f'https://{HOST}/cdx/search/cdx'
PLAYBACK = f'https://{HOST}/web/'
URL_FORM = r'https?://[^\s<>"]{3,1900}'
TEXT_TYPES = ('text/', 'application/xhtml', 'application/xml', 'application/json')
LIMIT_FILE = 'wayback-rate-limit.json'      # <state>/: epoch seconds until which no request goes to the archive after a 429 / 503 (this run)
CAVEAT = ('captured before T: the capture date is an upper bound of the existence of this content, not its publication date '
          '(the page may be older; a later edit is not visible, an earlier state is not served)')


def _limit_until():
    try: return float(json.loads((STATE / LIMIT_FILE).read_text()).get('until') or 0)
    except (OSError, ValueError, AttributeError): return 0.0


def _rate_limited(e=None):
    """Honest receipt of a 429 / 503 (or of a limit announced earlier in the run): no retry, no workaround, Retry-After respected."""
    now = time.time()
    if e is not None:
        try: ra = float(str((getattr(e, 'headers', None) or {}).get('Retry-After') or '').strip())
        except ValueError: ra = None
        until = now + (ra if ra and ra > 0 else 60.0)       # no Retry-After announced: a prudent minute, no request before
        try:
            STATE.mkdir(parents=True, exist_ok=True); (STATE / LIMIT_FILE).write_text(json.dumps({'until': until, 'code': e.code}))
        except OSError: pass
    else: until = _limit_until()
    wait = max(0, int(until - now) + 1)
    return {'status': 'rate_limited', 'refusal': f'rate_limited: the Internet Archive asked to slow down (HTTP 429/503); no request before {wait} s '
            '(Retry-After respected, no workaround); the source was not served', 'retry_after_s': wait}


def _check_url(url):
    return bool(re.fullmatch(URL_FORM, url)) and bool(urllib.parse.urlsplit(url).hostname) and '@' not in urllib.parse.urlsplit(url).netloc


def _last_capture(url, B):
    """-> (capture dict, None) | (None, receipt). The last capture with status 200 on/before the eve of T; the barrier is rechecked locally."""
    if time.time() < _limit_until(): return None, _rate_limited()
    q = urllib.parse.urlencode({'url': url, 'to': B.eve.strftime('%Y%m%d') + '235959', 'limit': -1, 'output': 'json', 'filter': 'statuscode:200',
                                'fl': 'timestamp,original,mimetype,statuscode,digest'}, quote_via=urllib.parse.quote)
    try: rows = json.loads(fetch(f'{CDX}?{q}') or b'[]')
    except urllib.error.HTTPError as e:
        if e.code in (429, 503): return None, _rate_limited(e)
        raise
    except json.JSONDecodeError: raise ProviderError('wayback: the CDX answer is not JSON')
    caps = [dict(zip(rows[0], r)) for r in rows[1:]] if rows and isinstance(rows[0], list) else []
    caps = [c for c in caps if re.fullmatch(r'\d{14}', c.get('timestamp') or '')]
    caps.sort(key=lambda c: c['timestamp'])
    for c in reversed(caps):                                                  # the latest first; the local barrier decides, not the provider
        d = f"{c['timestamp'][:4]}-{c['timestamp'][4:6]}-{c['timestamp'][6:8]}"
        if extra_ok(B, ['wayback:' + url], [d]): return dict(c, date=d), None
    return None, {'status': 'not_found', 'refusal': f'not_found: no archived capture (status 200) of this URL before {B.T} in the Internet Archive'}


def _item(url, c):
    return {'id': 'wayback:' + url, 'title': url, 'url': url, 'year': c['date'][:4], 'date': c['date'], 'captured': c['timestamp'], 'captured_before_T': CAVEAT,
            'dating': 'capture date (upper bound of existence, not publication date)', 'journal': 'Internet Archive', 'venue': 'Wayback Machine', 'type': 'web page',
            'mimetype': c.get('mimetype'), 'archive_url': f"{PLAYBACK}{c['timestamp']}id_/{c['original']}", 'doi': None}


def search_wayback(q, n, B):
    """q = a page URL -> ([the last capture before T], 1) or ([], 0). No content (read wayback:<url>). A receipt (not found, rate limited) -> [], note."""
    url = q.strip()
    if not _check_url(url): return [], 'expected a page URL (http:// or https://), e.g. https://example.org/page'
    c, rec = _last_capture(url, B)
    if rec: return [], rec['refusal']
    return [_item(url, c)], 1


def read_wayback(ident, B):
    """'wayback:<url>' -> the last capture before T with its raw content (text types only), or {'status', 'refusal'} (not_found, rate_limited)."""
    url = value(ident)
    if not _check_url(url): return {'refusal': 'expected form wayback:<page URL>, e.g. wayback:https://example.org/page'}
    c, rec = _last_capture(url, B)
    if rec: return rec
    it = _item(url, c); mt = (c.get('mimetype') or '').lower()
    if mt and not mt.startswith(TEXT_TYPES):
        return dict(it, text=None, text_note=f'capture content type {mt} is not text: not served (archive_url gives the bytes)')
    try: raw = fetch(it['archive_url'])
    except urllib.error.HTTPError as e:
        if e.code in (429, 503): return _rate_limited(e)
        if e.code in (404, 410): return {'status': 'not_found', 'refusal': 'not_found: the capture listed by the CDX is not served by the playback'}
        raise
    t = raw.decode('utf-8', 'replace')
    if 'html' in mt or re.match(r'\s*(<!doctype html|<html)', t[:200], re.I):
        t = re.sub(r'(?is)<(script|style|noscript)\b.*?</\1\s*>|<!--.*?-->', ' ', t); how = 'html, scripts and styles dropped, tags stripped'
    else: how = 'as archived'
    t = plain(t) if how != 'as archived' else t.strip()
    if not t: return dict(it, text=None, text_note='the captured page has no text')
    cut = len(t) > TEXT_HEAD
    return dict(it, text=t[:TEXT_HEAD] + (f' [... text cut at {TEXT_HEAD:,} of {len(t):,} characters ...]' if cut else ''), text_form=how, raw_bytes=len(raw))


SOURCE = {
    'name': 'wayback', 'order': 900,
    'engines': {'wayback': search_wayback},
    'ids': [{'prefix': 'wayback', 'form': URL_FORM}],
    'read': read_wayback, 'citing': EXTRA_NO_CHAIN, 'references': EXTRA_NO_CHAIN, 'related': RELATED_ONLY,
    'plugins': (), 'access': 'api',          # level 1: CDX server API + Memento (RFC 7089), decision of the owner 2026-11-01 (ACCESS-POLICY.md)
    # pacing declared here (not in config.json): 1 request per second, no parallel call; 429 / 503 stop at once (receipt rate_limited,
    # Retry-After respected through <state>/wayback-rate-limit.json), 403 stops too
    'hosts': {HOST: {'interval': 1.0, 'stop': (403, 429, 503)}},
    'terms': 'Internet Archive Wayback Machine, CDX server API and Memento playback, keyless; archived content belongs to its original rights holders',
    'barrier': 'provider side: to = eve of T (23:59:59); local: capture date < T through the barrier (forbidden URL refused); the capture date is an upper '
               'bound of the existence of the content, not its publication date (flagged in every receipt)',
    'key': None,
}
