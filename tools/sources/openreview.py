# SPDX-License-Identifier: Apache-2.0
"""OpenReview (/notes/search, API v1 and v2, forums only): search-openreview, read openreview:<forum id> (forum met by a search)."""
import datetime as dt
import json
import re
import urllib.error, urllib.parse, urllib.request
from sources._common import STATE, date_upper, jget, law_ok
from sources._common import RELATED_ONLY, preprint_unless_venue, value


OR_API = ('https://api.openreview.net/', 'https://api2.openreview.net/')   # API v1 (venues before 2023), API v2; /notes/search only
OR_SEEN = 'openreview'                                                      # <state>/openreview/<id>.json: forum notes met by a search (read needs them)
OR_VIS = ('cdate', 'tcdate', 'odate', 'pdate', 'mdate')                     # a forum note is visible when every present date is < T
OR_PENDING = r'(?i)^(submitted to\b|.*\bsubmission$|.*\bunder review\b)'     # venue strings that are not a decision
OR_MIRROR = ('dblp.org', 'openreview.net/archive', 'openreview.net/public_article')   # invitation prefixes (lower case) of mirrored records


def or_day(ms):
    """OpenReview millisecond timestamp -> ISO day (UTC); anything else -> None (refused by the barrier when required)."""
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).date().isoformat() if isinstance(ms, (int, float)) and ms > 0 else None


def or_val(c, k):
    v = (c or {}).get(k)
    return v.get('value') if isinstance(v, dict) else v                       # API v2 wraps every field in {"value": ...}


def or_dates(note, keys): return [or_day(note.get('cdate') or note.get('tcdate'))] + [or_day(note[k]) for k in keys if note.get(k) is not None]


def or_item(note, B, with_abstract=False):
    """Forum note (paper). Visible when cdate, tcdate, odate, pdate and mdate (those present) are < T. tmdate (true modification, also moved
    by platform migrations) gates the content: on/after T the abstract and the venue/decision are masked (a later revision may differ)."""
    c = note.get('content') or {}; title = or_val(c, 'title'); fid = note.get('forum') or note.get('id')
    if not fid or not law_ok(B, [fid, 'openreview:' + str(fid)], or_dates(note, OR_VIS), [title]): return None
    fresh = note.get('tmdate') is None or (or_day(note['tmdate']) is not None and date_upper(or_day(note['tmdate'])) < B.T)
    venue = or_val(c, 'venue') if fresh else None
    inv = note.get('invitation') or (note.get('invitations') or [''])[0]
    mirror = inv.lower().startswith(OR_MIRROR)                                # records mirrored or uploaded outside a reviewed venue: no decision
    decided = bool(venue) and not mirror and not re.match(OR_PENDING, venue)
    it = {'id': 'openreview:' + fid, 'openreview': fid, 'doi': None, 'title': title, 'year': or_day(note.get('cdate') or note.get('tcdate'))[:4],
          'date': or_day(note.get('cdate') or note.get('tcdate')), 'date_public': or_day(note.get('odate')), 'journal': 'OpenReview',
          'venue_id': inv.split('/-/')[0] or None, 'venue': venue, 'decision': venue if decided else None,
          'decision_date': (or_day(note.get('pdate')) or or_day(note.get('mdate')) or or_day(note.get('tmdate'))) if decided else None,
          'first_author': (or_val(c, 'authors') or [None])[0], 'type': 'record' if mirror else 'submission', 'url': 'https://openreview.net/forum?id=' + fid,
          'content': 'unchanged since before T' if fresh else 'modified on/after T (tmdate): abstract, venue and decision masked'}
    if with_abstract: it['abstract'] = ' '.join(str(or_val(c, 'abstract') or '(no abstract available)').split())[:6000] if fresh else '(masked: note modified on/after T)'
    return it


def or_search(api, q, n, source='forum', group='all'):
    return jget(api + 'notes/search?' + urllib.parse.urlencode({'term': q, 'type': 'terms', 'content': 'all', 'group': group, 'source': source, 'limit': n}))


def search_openreview(q, n, B):
    """OpenReview /notes/search (API v1 and v2), forums only. No provider-side date filter exists on this endpoint: local barrier only.
    /notes?id=, ?forum= and /notes/edits answer 403 ChallengeRequiredError (probe 2026-10-28): not used (ACCESS-POLICY.md, level 3)."""
    if not q.strip(): return [], 'empty query'
    per, seen, tot = [], set(), []
    for api in OR_API:
        r = or_search(api, q, n); out = []
        tot.append(str(r.get('count')))
        for note in r.get('notes') or []:
            fid = note.get('forum') or note.get('id')
            if fid in seen or note.get('replyto'): continue
            seen.add(fid)
            try:
                d = STATE / OR_SEEN; d.mkdir(parents=True, exist_ok=True)
                (d / (re.sub(r'[^A-Za-z0-9_-]', '_', fid) + '.json')).write_text(json.dumps(dict(note, _api=api)))
            except OSError: pass
            x = or_item(note, B)
            if x: out.append(x)
        per.append(out)
    out = [x for pair in zip(*per) for x in pair] + [x for o in per for x in o[min(map(len, per)):]]   # v1 and v2 interleaved
    return out[:n], f"provider counts v1 {tot[0]}, v2 {tot[1]} (capped at 10,000; no provider-side date filter: local barrier on cdate, tcdate, odate, pdate, mdate)"


def or_reply(note, B):
    """Review, meta-review, comment or decision: every present date (cdate, tcdate, mdate, tmdate) < T, else never served."""
    if not law_ok(B, [note.get('id')], or_dates(note, ('tcdate', 'mdate', 'tmdate')), []): return None
    c = note.get('content') or {}; inv = note.get('invitation') or (note.get('invitations') or [''])[0]; kind = inv.rsplit('/', 1)[-1]
    text = ' | '.join(f'{k}: {" ".join(str(or_val(c, k)).split())}' for k in c if k not in ('title',) and or_val(c, k) not in (None, ''))
    return {'id': note.get('id'), 'kind': 'decision' if or_val(c, 'decision') or kind == 'Decision' else kind, 'date': or_day(note.get('cdate') or note.get('tcdate')),
            'decision': or_val(c, 'decision'), 'rating': or_val(c, 'rating') or or_val(c, 'recommendation'), 'text': text[:4000]}


def read_openreview(fid, B):
    """Forum note met by an earlier search (the /notes?id= route is behind a challenge), then its public replies found by /notes/search
    (source=reply, title words, venue group), each under the barrier; a decision dated on/after T is never served."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{6,20}', fid): return {'refusal': 'expected form openreview:<forum id>, e.g. openreview:H1ewdiR5tQ'}
    f = STATE / OR_SEEN / (fid + '.json')
    if not f.exists(): return {'refusal': 'unknown forum: run search-openreview first (OpenReview serves a note by id only behind a challenge, not used)'}
    note = json.loads(f.read_text()); api = note.pop('_api', OR_API[1])
    it = or_item(note, B, with_abstract=True)
    if not it: return {'refusal': 'after T or forbidden'}
    reps = [x for x in (or_search(api, it['title'] or fid, 100, 'reply', it['venue_id'] or 'all').get('notes') or []) if x.get('forum') == fid and x.get('id') != fid]
    kept, late, late_dec = [], 0, False
    for r in reps:
        x = or_reply(r, B)
        if x: kept.append(x); continue
        late += 1; late_dec = late_dec or bool(or_val(r.get('content'), 'decision')) or (r.get('invitation') or (r.get('invitations') or [''])[0]).endswith('/Decision')
    dec = next((x for x in kept if x['kind'] == 'decision'), None)
    out = dict(it, reviews=[x for x in kept if x['kind'] != 'decision'], replies_found=len(reps), replies_after_T_or_forbidden=late,
               replies_note='replies found by title search (recall not guaranteed, decision notes often missed); comments CC BY 4.0 (OpenReview terms)')
    if dec: out.update(decision=dec['decision'], decision_date=dec['date'], decision_text=dec['text'])
    elif late_dec: out.update(decision=None, decision_date=None, venue=None, decision_masked='decision dated on/after T: not served (venue masked too)')
    return out


def read_openreview_ident(ident, B): return read_openreview(value(ident), B)


SOURCE = {
    'name': 'openreview', 'order': 130,
    'engines': {'openreview': search_openreview},
    'ids': [{'prefix': 'openreview', 'form': r'[\w-]{6,}', 'export': preprint_unless_venue, 'export_rank': 100}],
    'read': read_openreview_ident, 'related': RELATED_ONLY,              # citing / references: handed to the default source (unchanged since v0.4)
    'plugins': ('cs-ai',), 'access': 'api',
    'hosts': {'api.openreview.net': {'interval': 2.0, 'stop': (403, 429)}, 'api2.openreview.net': {'interval': 2.0, 'stop': (403, 429)}},   # 403 = challenge: stop
    'terms': 'OpenReview API, keyless; /notes?id= and /notes/edits behind a challenge: not used (ACCESS-POLICY level 3)',
    'barrier': 'no provider-side date filter: local only; a note is visible when every present date (cdate, tcdate, odate, pdate, mdate) < T; '
               'a decision dated on/after T is never served',
}
