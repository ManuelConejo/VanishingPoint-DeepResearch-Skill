# SPDX-License-Identifier: Apache-2.0
"""Provenance (code engine `provenance`, plugins/code.md): provenance <origin https://... | swh:1:...> -> Software Heritage visit or
object; code-file <origin>#<path>@<SHA> -> the whole file at the SHA (GitHub raw first for a GitHub origin, then Software Heritage). Optional SWH_TOKEN (1,200 req/h instead of 120). Client: code_sources.CodeClient."""
import re
import code_sources as sc

ORIGIN_FORM_MSG = 'expected form <origin https://... | swh:1:...>'


def run_provenance(g, arg, n, opt, B, extra):
    c = g.client
    return sc.Provenance(c).resolve(arg) if arg.startswith('swh:1:') else sc.Provenance(c).visit(arg, B.T)   # last visit before T


GITHUB_FINAL = ('commit_not_in_repository', 'commit_mismatch', 'file_not_found', 'binary', 'reference', 'repository')   # answers that stand: no fallback


def run_code_file(g, arg, n, opt, B, extra):
    """code-file <origin>#<path>@<SHA>: the whole file at the SHA (verifier, plugins/code.md verification rule 1); dated by the commit.
    A GitHub origin is read first on GitHub (code_sources.GitHubRepo: the commit resolved ON the named repository, then the raw file at the
    SHA, refused unless the commit is in the default branch history and the repository was created before T, GitHubRepo.gate); a definite
    GitHub answer (commit not in that repository or not in its default branch history, repository created on/after T, file absent, binary) stands, while a transport failure, a rate limit or
    offline mode falls back to Software Heritage (whose revision lookup does not check the origin: the fallback is marked in `github`)."""
    origin, path, sha = re.fullmatch(sc.CODE_FILE, arg).groups()
    repo = sc.github_repo_of(origin)
    if repo:
        gh = sc.GitHubRepo(g.client, extra)
        try:
            f = gh.file_at(repo, sha, path)
            why = gh.gate(f, B.T)                       # a definite answer: no Software Heritage fallback
            return {'refusal': f'GitHub: after T or not datable: {why} ({repo}@{sha[:12]}, {path})'} if why else f
        except ValueError as e:
            if str(e) in GITHUB_FINAL: return {'refusal': f'GitHub: {e} ({repo}@{sha[:12]}, {path})'}
            extra['github'] = f'not read on GitHub ({e}): Software Heritage tried (origin of the revision not checked there)'
        except RuntimeError as e: extra['github'] = f'not read on GitHub ({e}): Software Heritage tried (origin of the revision not checked there)'
    return sc.Provenance(g.client).file_text(arg)


def check_key(state):
    """Live check of SWH_TOKEN (setup_keys.py): one origin search (a rejected token is named in <state>/keys-invalid.json)."""
    sc.Provenance(sc.CodeClient(cache_dir=state)).origins('test', limit=1)
    return 'refused' if 'SWH_TOKEN' in sc.invalid_keys(state) else 'ok'


SOURCE = {
    'name': 'provenance', 'order': 47,
    'commands': {'provenance': {'engine': 'provenance', 'run': run_provenance, 'form': f'{sc.ORIGIN}|{sc.SWHID}', 'form_msg': ORIGIN_FORM_MSG,
                               'example': 'https://github.com/psf/requests'},
                 'code-file': {'engine': 'provenance', 'run': run_code_file, 'form': sc.CODE_FILE,
                               'form_msg': 'expected form <origin https://...>#<path>@<40-hex SHA>',
                               'example': 'https://github.com/psf/requests#README.md@' + '0' * 40}},
    'serves': ('software-heritage',),
    'plugins': ('code',), 'access': 'api',
    'hosts': {'archive.softwareheritage.org': {}},                            # config.json code_intervals: 6 s, 3 s with the token
    'terms': 'Software Heritage API terms of use; token optional (rate limit)',
    'barrier': 'origin: the last visit with a snapshot dated before T (visit list, never the latest visit), none -> refusal "unavailable before T"; '
               'visit date (or object date) < T, else refused (Gateway._date_filter)',
    'key': {'vars': ('SWH_TOKEN',), 'send': 'bearer', 'hosts': ('archive.softwareheritage.org',), 'without': 'degraded',
            'source': 'software-heritage', 'engine': 'provenance',
            'reason': '120 req/h instead of 1,200 (interval 6 s instead of 3 s)', 'free': 'free, account',
            'url': 'https://archive.softwareheritage.org/ (profile -> API token)', 'suggest': ('Software Heritage', '~2 min', True),
            'labels': ['Software Heritage'], 'check': check_key},
}
