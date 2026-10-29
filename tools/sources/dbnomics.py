# SPDX-License-Identifier: Apache-2.0
"""DBnomics (keyless, level 2 `page` cadence): search-dbnomics, read dbnomics:<provider>/<dataset>/<series>; CURRENT values only,
each one marked as_of "now" (possibly revised after T)."""
import itertools
import re
import urllib.error, urllib.parse, urllib.request
from sources._common import extra_ok, jget, tokens
from sources._series import AS_OF_NOW, DATA_CFG, data_forbidden, obs_before_T, obs_cap
from sources._common import value
from sources._series import DATA_NO_CHAIN


# ---------------------------------------------------------------- finance data series (plugins/finance.md sections 7-8): dbnomics, fred
# A series value for period P is published, then often REVISED. "Known at T" = periods ending before T AND values as published before T.
# FRED/ALFRED gives true vintages (realtime_start = realtime_end = eve of T); DBnomics serves CURRENT values only: each one is marked as_of "now".
# Neither serves release dates: a period ending before T may have been released on/after T (DBnomics) - flagged, never hidden.
DBNOMICS = 'https://api.db.nomics.world/v22/'
DBN_CAVEAT = ('current values as DBnomics serves them today (possibly revised after T); a period ending before T may have been released on/after T '
              '(no release date served); not the as-of-T value')
SERIES_ID = r'[A-Za-z0-9_.@+-]+/[A-Za-z0-9_.@+-]+/[A-Za-z0-9_.@+%:=-]+'   # dbnomics:<provider>/<dataset>/<series>


# DBnomics (keyless aggregator: ECB, Eurostat, IMF, OECD, INSEE, BIS, World Bank...). Search = datasets (/search), then series of the best datasets
# (/series/<provider>/<dataset>?q=), both re-ranked locally by query tokens (search_dbnomics); read = observations of one series. indexed_at is the LAST re-indexing, not a first-availability date: not a barrier.

def dbn_item(s):
    sid = f"{s.get('provider_code')}/{s.get('dataset_code')}/{s.get('series_code')}"
    return {'id': 'dbnomics:' + sid, 'title': s.get('series_name'), 'provider': s.get('provider_code'), 'dataset': s.get('dataset_code'),
            'dataset_name': s.get('dataset_name'), 'frequency': s.get('@frequency') or (s.get('dimensions') or {}).get('FREQ'), 'type': 'dataset',
            'last_reindexed': (s.get('indexed_at') or '')[:10] or None, 'url': 'https://db.nomics.world/' + sid}   # informative, not a barrier date


def dbn_score(qt, text):
    """(share of the query's tokens found in a name, share of the name's tokens that are query tokens): the local relevance of the
    ranking, coverage first, then the more specific name ('Unemployment rate by sex and age' before a long name that also mentions both)."""
    tt = tokens(text or '')
    return len(qt & tt) / max(1, len(qt)), len(qt & tt) / max(1, len(tt))


def search_dbnomics(q, n, B):
    """The DBnomics dataset search (/search) ranks datasets by their number of matching series, so a huge dataset whose name says
    nothing of the query comes first and fills every result. Here: a pool of data_series.dbnomics_candidates datasets (one request),
    case duplicates merged, ranked by the query tokens in the dataset name (dbn_score), then by the share of the dataset's series that
    match (a dataset about the query rather than one mentioning it), then DBnomics' order; the best dbnomics_datasets are opened, up to
    dbnomics_series_pool series each (/series/<provider>/<dataset>?q=), ranked the same way on the series name (dbn_score) and
    interleaved across datasets. Same number of requests as before (1 + dbnomics_datasets)."""
    qt = tokens(q)
    r = jget(DBNOMICS + 'search?' + urllib.parse.urlencode({'q': q, 'limit': int(DATA_CFG['dbnomics_candidates'])})).get('results') or {}
    pool, seen = [], set()
    for i, d in enumerate(r.get('docs') or []):
        k = (str(d.get('provider_code')), str(d.get('code') or '').lower())
        if not d.get('nb_matching_series') or k in seen: continue
        seen.add(k)
        share = d['nb_matching_series'] / max(1, d.get('nb_series') or d['nb_matching_series'])
        cov, spec = dbn_score(qt, d.get('name') or d.get('code'))
        pool.append((-cov, -spec, -share, i, d))
    lists = []
    for *_, d in sorted(pool, key=lambda x: x[:4])[:int(DATA_CFG['dbnomics_datasets'])]:
        path = '/'.join(urllib.parse.quote(str(d.get(k) or ''), safe='') for k in ('provider_code', 'code'))
        try: ss = jget(DBNOMICS + f'series/{path}?' + urllib.parse.urlencode({'q': q, 'limit': int(DATA_CFG['dbnomics_series_pool']), 'observations': 0})).get('series') or {}
        except urllib.error.HTTPError as e:
            if e.code == 404: continue
            raise
        docs = list(enumerate(ss.get('docs') or []))
        lists.append([s for _, s in sorted(docs, key=lambda x: (tuple(-v for v in dbn_score(qt, x[1].get('series_name'))), x[0]))])
    out = []
    for s in (x for row in itertools.zip_longest(*lists) for x in row if x is not None):   # interleaved: one dataset never fills n alone
        if len(out) >= n: break
        it = dbn_item(s)
        if not data_forbidden(B, [it['id']], [it['title']]):   # no first-availability date: the read checks existence by an observation before T
            out.append(dict(it, dating='existence before T checked at read (an observation period ending before T); values: ' + AS_OF_NOW))
    return out[:n], r.get('num_found')


def read_dbnomics(sid, B):
    if not re.fullmatch(SERIES_ID, sid): return {'refusal': 'expected form dbnomics:<provider>/<dataset>/<series>, e.g. dbnomics:ECB/ICP/M.U2.N.000000.4.ANR'}
    try: r = jget(DBNOMICS + 'series/' + '/'.join(urllib.parse.quote(x, safe='') for x in sid.split('/', 2)) + '?observations=1')
    except urllib.error.HTTPError as e:
        if e.code in (400, 404): return {'refusal': 'not found'}
        raise
    docs = (r.get('series') or {}).get('docs') or []
    if not docs: return {'refusal': 'not found'}
    s = docs[0]; it = dbn_item(s)
    keep, drop = obs_before_T([(p, v, None, {'as_of': AS_OF_NOW}) for p, v in zip(s.get('period') or [], s.get('value') or [])], B)
    if not keep or not extra_ok(B, [it['id']], [keep[-1]['period_end']], [it['title']]):
        return {'refusal': 'no observation period ending before T, or forbidden'}
    keep, note = obs_cap(keep); pv = r.get('provider') or {}
    return dict(it, date=keep[-1]['period_end'], as_of=AS_OF_NOW, vintage=None, caveat=DBN_CAVEAT, observations=keep, dropped_at_or_after_T=drop,
                **({'truncated': note} if note else {}), terms_of_use=pv.get('terms_of_use'),
                licence='DBnomics aggregation ODbL; data under the licence and terms of use of the original provider (terms_of_use)')


def read_dbnomics_ident(ident, B): return read_dbnomics(value(ident), B)


SOURCE = {
    'name': 'dbnomics', 'order': 200,
    'engines': {'dbnomics': search_dbnomics},
    'ids': [{'prefix': 'dbnomics', 'form': r'[\w.@+-]+/[\w.@+-]+/[\w.@+%:=-]+', 'export': 'dataset', 'export_rank': 80}],
    'read': read_dbnomics_ident, 'citing': DATA_NO_CHAIN, 'references': DATA_NO_CHAIN, 'related': DATA_NO_CHAIN,
    'plugins': ('finance',), 'access': 'page',
    'hosts': {'api.db.nomics.world': {'interval': 2.0, 'stop': (403, 429)}},   # robots Disallow / on the API host, rate not published -> level-2 pacing
    'terms': 'DBnomics API (CEPREMAP), keyless; each series under the terms of its provider',
    'barrier': 'local: observations kept only when their period ends before T; values are current (as_of "now"), release dates not served (flagged)',
    'as_of': 'now: current values, possibly revised after T; a period ending before T may have been released on/after T',
}
