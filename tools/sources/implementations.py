"""How other projects implement X (code engine `implementations`, served with plugins/code.md through enabled_by: sourcegraph, github):
find-implementations "<literal>[ OR <literal> ...]" [--language L] [--ecosystem pypi|npm|cargo|...] [--path P] [--n N]
-> distinct repositories ranked (the most used packages of the ecosystem first, then stars), forks / vendored copies / same-content copies
removed and listed apart, each with its best matching file cited repo:<owner>/<name>/<path>:<a>-<b>@<SHA40>. Typed filters lang:, eco: /
ecosystem:, file: / path: are also read inside the argument. Client: code_sources.Implementations (Sourcegraph keyless, ecosyste.ms
keyless, GitHub code search only with VP_GITHUB_TOKEN, GitHub REST for dating). Bounds: config.json `implementations`."""
import re
import code_sources as sc

TYPED = re.compile(r'(?:(?<=\s)|^)(lang|language|eco|ecosystem|file|path|f):(\S+)(?=\s|$)', re.I)
TYPED_KEY = {'lang': 'language', 'language': 'language', 'eco': 'ecosystem', 'ecosystem': 'ecosystem', 'file': 'path', 'path': 'path', 'f': 'path'}
CODES = {'query_invalid': 'empty, too long or control characters in a literal', 'too_many_alternatives':
         f"at most {sc.IMPL['max_alternatives']} literals joined by ' OR ' (config.json implementations.max_alternatives)",
         'filter_invalid': 'a filter value outside [A-Za-z0-9_.+/#-]', 'ecosystem': 'unknown ecosystem; known: ' + ', '.join(sc.USAGE_REGISTRY)}


def run_find_implementations(g, arg, n, opt, B, extra):
    """Typed filters taken out of the argument (one value each, a conflict with an option is refused), then code_sources.Implementations.find.
    Its own barrier: a pinned repository is dated by GitHubRepo.barrier (gate, committer date before T, backdate signals); the others carry the
    live index commit, marked undated (dating)."""
    f = {k: opt.get(k) for k in ('language', 'ecosystem', 'path')}
    for m in TYPED.finditer(arg):
        k, v = TYPED_KEY[m.group(1).lower()], m.group(2)
        if f.get(k) and f[k] != v: return {'refusal': f'find-implementations: {k} given twice with two values ({f[k]!r} and {v!r})'}
        f[k] = v
    pattern = ' '.join(TYPED.sub(' ', arg).split())
    if not pattern: return {'refusal': 'find-implementations: empty pattern once the filters are taken out; give the code text to look for'}
    if f.get('ecosystem'): f['ecosystem'] = f['ecosystem'].lower()
    try: return sc.Implementations(g.client, extra).find(pattern, B, language=f['language'], ecosystem=f['ecosystem'], path=f['path'], n=n)
    except ValueError as e:
        if str(e) in CODES: return {'refusal': f'find-implementations: {e} ({CODES[str(e)]})'}
        raise


SOURCE = {
    'name': 'implementations', 'order': 45,
    'enabled_by': ('sourcegraph', 'github'),                           # plugins/code.md declares both: served with the code plugin
    'commands': {'find-implementations': {'engine': 'implementations', 'run': run_find_implementations, 'date_filter': False,
                                          'example': '"Retry-After" --language python'}},
    'plugins': ('code',), 'access': 'api',
    'hosts': {'sourcegraph.com': {}, 'packages.ecosyste.ms': {}, sc.GH_API_HOST: {}, sc.GH_RAW_HOST: {}},   # CodeClient: closed host list, code_intervals
    'terms': 'Sourcegraph public search API (keyless); ecosyste.ms packages API (keyless, data CC BY-SA 4.0); GitHub REST API (read-only token optional, '
             'api host only; GitHub code search needs it) and raw file host',
    'barrier': 'the first implementations.pinned_repos repositories: cited commit dated like repo-file (default branch history, repository created before T, '
               'committer date before T, backdate signals), an indexed commit on/after T replaced by the last commit of the default branch before T; '
               'lines re-read in the file at the dated commit; the others: live index commit, dating "absent", no citation form; popularity (stars, ecosystem rank) observed now',
    'as_of': 'now: stars and ecosystem ranks are observed at the call',
}
