# SPDX-License-Identifier: Apache-2.0
"""TEMPLATE of a source: copy this file to tools/sources/<name>.py (built-in) or ~/.config/vp/sources/<name>.py (user source,
loaded with VP_USER_SOURCES=1), rename, fill in. Files starting with `_` are never loaded as sources: this one is only a model.
It describes a fictitious keyless API (api.example.org) that has a search with a date filter and a record endpoint.
Read CONTRIBUTING.md first (barrier rules, access policy, keys, tests). Standard library only."""
import urllib.parse

# Shared helpers: fetch / jget (cache, per-host pacing, stop codes, retries), the date barrier (Barrier, B.ok, extra_ok, law_ok,
# date_upper, year_before_T, _before) and messages. Import them by name: tests and tools replace gateway.fetch / gateway.STATE and the
# registry rebinds the same names in every source module (never copy fetch into your module).
from sources._common import EXTRA_NO_CHAIN, RELATED_ONLY, extra_ok, jget, value
from sources.crossref import doi_recheck   # items carrying a DOI pass only when Crossref attests deposit AND publication < T

API = 'https://api.example.org/v1/'


def example_item(r, B):
    """One record -> the item served, or None when the barrier refuses it (B.excluded is counted by extra_ok / B.ok).
    Every date that may be on/after T is checked: publication AND indexing (or deposit, last version...). No usable date -> refused
    (strict): extra_ok / B.ok refuse a None date. Never fabricate precision: a year alone is passed through year_before_T (kept only when
    strictly before the year of T); a partial date is read as its UPPER bound by date_upper (2024-05 -> 2024-05-30)."""
    rid = r.get('id')
    if not rid or not extra_ok(B, [r.get('doi'), rid, 'example:' + rid], [r.get('published'), r.get('indexed')], [r.get('title')]): return None
    return {'id': 'example:' + rid, 'doi': r.get('doi'), 'title': r.get('title'), 'year': (r.get('published') or '')[:4], 'date': r.get('published'),
            'journal': 'Example', 'type': 'article'}


def search_example(q, n, B):
    """-> (items, total or a note). Provider-side filter at the EVE of T whenever the API has one (here `until=`), so that the n slots are
    not spent on post-T records; the local recheck (example_item) is applied anyway: never trust the provider filter alone."""
    r = jget(API + 'search?' + urllib.parse.urlencode({'q': q, 'rows': n, 'from': B.start.isoformat(), 'until': B.eve.isoformat()}))
    out = [x for x in (example_item(h, B) for h in r.get('hits') or []) if x]
    return doi_recheck(out, B)[:n], r.get('total')


def read_example(ident, B):
    """'example:<id>' (stripped) -> the record and its text, or {'refusal': '...'} (after T, forbidden, not found). Never an empty dict."""
    rid = value(ident)
    try: r = jget(API + 'records/' + urllib.parse.quote(rid))
    except Exception: return {'refusal': 'not found'}
    it = example_item(r, B)
    if not it: return {'refusal': 'after T, forbidden or undated'}
    return dict(it, abstract=(r.get('abstract') or '(no abstract available)')[:6000])


SOURCE = {
    'name': 'example',                 # unique, lower case; also the name used in a plugin's ```sources block when it is the engine name
    'order': 1000,                     # display position only (lists of sources, keys, identifier kinds); keep the default
    'engines': {'example': search_example},   # engine -> search(q, n, B); command search-example. With options:
                                       #   {'example': {'search': fn, 'options': ('date_from', 'date_to')}} (passed by Gateway.call)
    # 'commands': {...}                # code engines only (see code_search.py, versions.py): {cmd: {engine, run(g, arg, n, opt, B, extra),
                                       #   form, form_msg, example, date_filter}}; 'serves': plugin names served by that code engine;
                                       #   'enabled_by': plugin names whose declaration also enables that code engine (github -> github-repo)
    'ids': [{'prefix': 'example',      # identifier `example:<value>`, routed by gateway read; card / result.json field of the same name
             'form': r'[A-Za-z0-9]+',  # accepted value in result.json (validate_result.py)
             'export': 'article',      # export_data type: article preprint paper thesis dataset software standard trial case legislation report
             'export_rank': 110}],     # (or a callable(ident, venue)); lowest rank wins when a source carries several identifiers
                                       # law sources add 'law_form' (strict form used by law_checks.py)
    # 'match': fn(ident) -> bool       # optional: claim identifiers without a declared prefix (bare PMIDs, preprint DOIs)
    'read': read_example,
    'citing': EXTRA_NO_CHAIN,          # citation chaining: a callable(ident, n, B) -> (items, total), or a "not served" message;
    'references': EXTRA_NO_CHAIN,      #   an absent entry hands the identifier to the default source (DOI chaining)
    'related': RELATED_ONLY,
    'plugins': ('cs-ai',),             # informative: the plugins that list this engine in their ```sources block
    'access': 'api',                   # ACCESS-POLICY.md level: api | page | browser (tos_forbidden / technical_block are never wired)
    'hosts': {'api.example.org': {'interval': 1.0, 'stop': (403, 429)}},   # every host called: seconds between calls, codes that stop at
                                       #   once (no retry), optional 'timeout' (s). Level 2 `page` sources: interval >= 2.0, stop on 403/429
    'terms': 'Example API terms of use, keyless; records under CC0',       # licence / terms, as published by the provider
    'barrier': 'provider side: until = eve of T; local: publication AND indexing dates < T; DOIs rechecked on Crossref',
    # 'as_of': 'now: ...'              # data that exist only as current values: say so here AND mark every record as_of "now"
    'key': None,
}

# A source with an optional key adds a key spec (see pubmed.py, openalex.py, fred.py, piste.py, code_search.py):
#   'key': {'vars': ('EXAMPLE_KEY',),                 # resolved by key(): env EXAMPLE_KEY, then ~/.config/vp/example_key.key
#           'send': 'query:api_key',                  # how: query:<param> | bearer | header:<Name> | oauth-client-credentials
#           'hosts': ('api.example.org',),            # the ONLY hosts the key may be sent to (the contract test checks it)
#           'without': 'degraded',                    # degraded (slower / smaller budget) | skipped (0 request, a receipt)
#           'reason': '100 req/day instead of 10,000', 'free': 'free, account', 'url': 'https://example.org/keys',
#           'suggest': ('Example', '~2 min', True),   # check_keys --suggest: name, registration delay, may be proposed
#           'labels': ['Example'], 'check': check_key,   # setup_keys --check: check_key(state) -> 'ok' | 'refused'
#           'rejected': {'codes': (401, 403), 'markers': (b'',)},   # query:api_key only: fetch drops a rejected key, retries once
#           'interval_with_key': {'api.example.org': 0.2}}           # faster pacing while the key is live
# Never put a key in a URL except as the declared query parameter to a declared host; never in a receipt, a journal or an error.
# A `skipped` source raises its own skip exception before any request (see fred.py DataSkip / data_engine, piste.py PisteSkip).
