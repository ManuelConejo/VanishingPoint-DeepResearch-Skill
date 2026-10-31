# SPDX-License-Identifier: Apache-2.0
"""Code search (code engine `code`, plugins/code.md): search-code "<pattern>" [--language L] [--repo owner/repo] [--path P] over Sourcegraph and,
with VP_GITHUB_TOKEN, GitHub (else the GitHub side is skipped, credential_missing; Sourcegraph continues). Client: code_sources.CodeClient.
Filters typed inside the pattern (repo:, lang:, file:/path:) are taken out and applied as filters (code_sources.split_filters). A Sourcegraph
rate limit or challenge does not lose the call: `sourcegraph` in the answer types it (status, until_utc, advice), results stay a list."""
import time
import code_sources as sc


SG_STATUS = {'rate_limited': 'rate_limited', 'bot_challenge': 'blocked'}


def run_search_code(g, arg, n, opt, B, extra):
    try: pattern, typed = sc.split_filters(arg)
    except ValueError as e: return {'refusal': f'search-code: {e} (filters typed in the pattern: repo:<owner>/<name>, lang:<language>, file:<path>, one value each)'}
    f = dict(language=opt.get('language'), repo=opt.get('repo'), path=opt.get('path'))
    for k, v in typed.items():
        if f.get(k) and f[k] != v: return {'refusal': f'search-code: {k} given twice with two values ({f[k]!r} and {v!r} typed in the pattern)'}
        f[k] = v
    if typed: extra['filters_from_pattern'] = typed
    if not pattern.strip(): return {'refusal': 'search-code: empty pattern once the filters are taken out; give the code text to search (filters alone list nothing)'}
    cs = sc.CodeSearch(g.client); f['limit'] = n
    try: res = cs.search(pattern, 'sourcegraph', **f)
    except ValueError as e:
        if str(e) not in SG_STATUS: raise
        st = cs.sourcegraph_stopped(); until = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(st[0])) if st else None
        res = []
        extra['sourcegraph'] = {'status': SG_STATUS[str(e)], 'reason': str(e) + (': Cloudflare challenge (cf-mitigated), a technical block never circumvented (ACCESS-POLICY.md)'
                                if str(e) == 'bot_challenge' else ': Sourcegraph keyless rate limit, bounded retries done'),
                                'until_utc': until, 'advice': 'no Sourcegraph request before until_utc (later search-code calls return at once); '
                                'for a named repository use repo-head, repo-tree and repo-file (engine github-repo)'}
    try: gh = cs.search(pattern, 'github', **f)                           # GitHub only with a token, else skipped; its typed error does not lose Sourcegraph
    except ValueError as e: gh = {'status': 'error', 'reason': str(e)}
    if isinstance(gh, dict): extra['github'] = gh
    else: res += gh
    return res


def check_key(state):
    """Live check of VP_GITHUB_TOKEN (setup_keys.py): one GitHub code search through CodeSearch (401/403 or invalid token -> refused)."""
    try:
        r = sc.CodeSearch(sc.CodeClient(cache_dir=state)).search('test', provider='github', limit=1)
        return 'ok' if isinstance(r, list) else 'refused'
    except ValueError as x:
        if str(x) not in ('credential_invalid', 'provider_error:HTTP401', 'provider_error:HTTP403'): raise
        return 'refused'


SOURCE = {
    'name': 'code', 'order': 44,
    'commands': {'search-code': {'engine': 'code', 'run': run_search_code}},
    'serves': ('github', 'sourcegraph'),
    'ids': [{'prefix': 'code', 'read': False},                                 # card field `code`: `<file path>@<SHA>` (SKILL.md section 0)
            {'prefix': 'local', 'form': r'\S+@[0-9a-f]{7,40}', 'read': False, 'card': False}],   # result.json id `local:<path>@<SHA>`
    'plugins': ('code',), 'access': 'api',
    'hosts': {'api.github.com': {}, 'sourcegraph.com': {}},                     # CodeClient: closed host list, pacing in config.json code_intervals
    'terms': 'Sourcegraph public search API; GitHub REST API (read-only token, never logged, sent to api.github.com only)',
    'barrier': 'live index: results cannot be dated (dating "absent", warning); every dated result >= T removed (Gateway._date_filter)',
    'key': {'vars': ('VP_GITHUB_TOKEN',), 'send': 'bearer', 'hosts': ('api.github.com',), 'without': 'skipped',
            'source': 'github (GitHub side of search-code)', 'engine': 'code',
            'reason': 'search/code and GraphQL require a token: {"status":"skipped","reason":"credential_missing"}; Sourcegraph continues',
            'free': 'free, GitHub account, read-only token', 'url': 'https://github.com/settings/tokens',
            'suggest': ('GitHub search/code', '~2 min, read-only token', True), 'labels': ['GitHub code search'], 'check': check_key,
            'present': lambda: sc.read_token()},                                 # late-bound: tests replace sc.read_token
}
