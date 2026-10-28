# SPDX-License-Identifier: Apache-2.0
"""FRED / ALFRED (St. Louis Fed): search-fred, read fred:<series id> at the vintage of the eve of T. FRED_API_KEY required
(free), else skipped with 0 request (key-less alternative: search-dbnomics)."""
import json
import re
import code_sources as sc
import urllib.error, urllib.parse, urllib.request
from sources._common import STATE, extra_ok, jget, key
from sources._series import DataSkip, data_engine, obs_before_T, obs_cap
from sources._common import Barrier, value
from sources._series import DATA_NO_CHAIN


FRED = 'https://api.stlouisfed.org/fred/'
FRED_ID = r'[A-Za-z0-9_.-]{1,40}'


# FRED / ALFRED (St. Louis Fed, free key FRED_API_KEY sent as api_key=, never shown). Vintage = eve of T: values as KNOWN that day.

def fred_key():
    k = key('FRED_API_KEY')
    if not k: raise DataSkip('credential_missing', 'FRED_API_KEY absent (free key, KEYS.md); 0 request; key-less alternative: search-dbnomics')
    if 'FRED_API_KEY' in sc.invalid_keys(STATE): raise DataSkip('key_invalid', 'FRED refused FRED_API_KEY earlier in this run; 0 request; key-less alternative: search-dbnomics')
    return k


def fred_json(path, B, **params):
    """GET <FRED>/<path> at the vintage of the eve of T. 400 about api_key -> key marked invalid, DataSkip; other 400 -> ValueError(message)."""
    k = fred_key()
    q = dict(params, realtime_start=B.eve.isoformat(), realtime_end=B.eve.isoformat(), file_type='json')
    try: return jget(FRED + path + '?' + urllib.parse.urlencode(q) + '&api_key=' + urllib.parse.quote(k))
    except urllib.error.HTTPError as e:
        if e.code != 400: raise
        try: msg = str(json.loads(e.read() or b'{}').get('error_message') or '')
        except ValueError: msg = ''
        msg = msg.replace(k, '***')[:200]
        if 'api_key' in msg.lower(): sc.mark_invalid(STATE, 'FRED_API_KEY'); raise DataSkip('key_invalid', 'FRED refused FRED_API_KEY (HTTP 400); key-less alternative: search-dbnomics')
        raise ValueError(msg or 'HTTP 400')


def fred_item(s, B):
    sid = s.get('id')
    if not sid or not extra_ok(B, [sid, 'fred:' + sid], [s.get('observation_start')], [s.get('title')]): return None
    return {'id': 'fred:' + sid, 'title': s.get('title'), 'frequency': s.get('frequency_short') or s.get('frequency'), 'units': s.get('units'),
            'seasonal_adjustment': s.get('seasonal_adjustment_short'), 'observation_start': s.get('observation_start'), 'type': 'dataset',
            'as_of': B.eve.isoformat() + ' (ALFRED vintage: metadata as known on the eve of T)', 'url': 'https://alfred.stlouisfed.org/series?seid=' + sid}


@data_engine(True)
def search_fred(q, n, B):
    r = fred_json('series/search', B, search_text=q, limit=n)
    return [x for x in (fred_item(s, B) for s in r.get('seriess') or []) if x][:n], r.get('count')


@data_engine(False)
def read_fred(sid, B):
    if not re.fullmatch(FRED_ID, sid): return {'refusal': 'expected form fred:<series id>, e.g. fred:UNRATE'}
    try:
        meta = (fred_json('series', B, series_id=sid).get('seriess') or [None])[0]
        it = fred_item(meta or {}, B)
        if not it: return {'refusal': 'not found, after T or forbidden'}
        r = fred_json('series/observations', B, series_id=sid, observation_end=B.eve.isoformat(), **({'observation_start': B.start.isoformat()} if B.since else {}))
    except ValueError as e: return {'refusal': f'not served at the vintage of the eve of T ({e})'}
    fq = (meta.get('frequency_short') or '').upper()
    rows = [(o.get('date'), o.get('value'), fq, {'vintage': o.get('realtime_start')}) for o in r.get('observations') or []
            if (o.get('realtime_start') or '9999') <= B.eve.isoformat()]   # a value published after the eve of T never passes
    keep, drop = obs_before_T(rows, B)
    if not keep: return {'refusal': 'no observation period ending before T at the vintage of the eve of T'}
    keep, note = obs_cap(keep)
    return dict(it, date=keep[-1]['period_end'], as_of=B.eve.isoformat() + ' (ALFRED vintage: values as known on the eve of T)', vintage=B.eve.isoformat(),
                observations=keep, dropped_at_or_after_T=drop, **({'truncated': note} if note else {}),
                licence='FRED terms of use; some series are copyrighted by their source (notes of the series)')


def read_fred_ident(ident, B): return read_fred(value(ident), B)


def check_key(state):
    """Live check of FRED_API_KEY (setup_keys.py): one search through the FRED engine (400 about api_key -> key_invalid)."""
    import datetime as _dt
    x = search_fred('unemployment', 1, Barrier(_dt.date.today()))[0]
    return 'refused' if isinstance(x, dict) and x.get('reason') == 'key_invalid' else 'ok'


SOURCE = {
    'name': 'fred', 'order': 210,
    'engines': {'fred': search_fred},
    'ids': [{'prefix': 'fred', 'form': r'[A-Za-z0-9_.-]{1,40}', 'export': 'dataset', 'export_rank': 80}],
    'read': read_fred_ident, 'citing': DATA_NO_CHAIN, 'references': DATA_NO_CHAIN, 'related': DATA_NO_CHAIN,
    'plugins': ('finance',), 'access': 'api',
    'hosts': {'api.stlouisfed.org': {'interval': 2.0, 'stop': (400, 403, 404, 429)}},   # robots Crawl-delay 2; 400 = key or argument error: never retried
    'terms': 'FRED API terms of use (free key); some series are copyrighted by their source (notes of the series)',
    'barrier': 'ALFRED vintage = eve of T (realtime_start = realtime_end): values as known that day; observations kept only when their period ends before T',
    'key': {'vars': ('FRED_API_KEY',), 'send': 'query:api_key', 'hosts': ('api.stlouisfed.org',), 'without': 'skipped',
            'reason': 'FRED / ALFRED: 0 request, credential_missing (the API returns 400 without a key); search-dbnomics stays (current values)',
            'free': 'free, FRED account', 'url': 'https://fred.stlouisfed.org/docs/api/api_key.html',
            'suggest': ('FRED / ALFRED', '~2 min', True), 'labels': ['FRED / ALFRED'], 'check': check_key},
}
