"""Exact code search in a NAMED GitHub repository at a commit dated before T, without any search API (code engine repo-grep, served with
plugins/code.md through enabled_by: github): repo-grep <owner>/<name>[@<SHA>] <fixed string> [--path P] [--n N] -> every line holding the
fixed string at that commit (git grep -F, case-sensitive, binary files skipped), each cited repo:<owner>/<name>/<path>:<line>@<SHA40>
(tools/check_code_refs.py form); no line = the string is absent at that commit (under P), an exact negative a live index cannot give.
repo-ls <owner>/<name>[@<SHA>] [--path P] -> the file paths and sizes at the commit (submodules listed, never followed).
The commit: the SHA given, resolved and dated like repo-file (GitHubRepo.resolve + barrier: default branch history, repository created
before T, committer date before T, backdate checks), else the last commit of the default branch before T (repo-head, GitHubRepo.head_gated).
Then ONE commit is fetched keyless over https into a bare repository of the cache <state>/<repo_grep.cache_dir> (tools/repo_snapshot.py:
no history, no checkout, nothing of the repository executed). git absent, fetch refused or over repo_grep.max_fetch_bytes -> a typed
answer (status git_missing | fetch_failed | too_large | commit_missing | git_failed) naming the API tools to fall back on. Bounds:
config.json repo_grep."""
import re
import code_sources as sc
import repo_snapshot as rs

WEB = r'(?:repo:|' + re.escape(sc.GH['web']) + r')?'
GREP_FORM = WEB + r'(' + sc.GH_REPO + r')(?:@([0-9a-f]{7,40}))?\s+(\S.*)'
LS_FORM = WEB + r'(' + sc.GH_REPO + r')(?:@([0-9a-f]{7,40}))?'
FILE_ORIGINS = None   # tests only: {<owner>/<name>: local directory} fetched through file:// (None: https://github.com/<owner>/<name> only)
FALLBACK = 'fall back on the API tools: repo-tree {repo}@{sha} | repo-file {repo}/<path>@{sha} | search-code "<pattern>" --repo {repo}'


def _commit(g, repo, sha, B, extra):
    """The commit to read: the SHA given (resolved on the named repository, then GitHubRepo.barrier), else the last commit of the default
    branch before T (head_gated). -> (resolved commit, None) or (None, refusal text)."""
    gh = sc.GitHubRepo(g.client, extra)
    if not sha: return gh.head_gated(repo, B, extra)
    r = gh.resolve(repo, sha)
    why = gh.barrier(repo, r, B, extra)
    return (None, why) if why else (r, None)


def _path(opt):
    """--path: a repository-relative path or directory (literal pathspec), else None; '' when absent."""
    p = (opt.get('path') or '').strip().rstrip('/')
    return p if not p or sc.path_ok(p) else None


def _snapshot(g):
    return rs.Snapshot(g.state / rs.RG['cache_dir'], file_origins=FILE_ORIGINS)


def _failed(e, repo, sha):
    return {'status': e.code, 'reason': e.reason, 'repo': repo, 'sha': sha, 'results_served': 0,
            'fallback': FALLBACK.format(repo=repo, sha=sha or '<SHA>')}


def _dated(r, repo):
    return dict(repo=repo, sha=r['sha'], date=r.get('date'), membership=r.get('membership'), backdate_check=r.get('backdate_check'))


def run_repo_grep(g, arg, n, opt, B, extra):
    """repo-grep <owner>/<name>[@<SHA>] <fixed string> [--path P]: git grep -F of the string at the commit (after the barrier)."""
    repo, sha, pattern = re.fullmatch(GREP_FORM, arg).groups()
    pattern = pattern.rstrip()
    if len(pattern) > 1 and pattern[0] == pattern[-1] == '"': pattern = pattern[1:-1]      # one pair of surrounding quotes is not searched
    if not pattern or len(pattern) > int(rs.RG['pattern_max_chars']) or any(ord(c) < 32 or ord(c) == 127 for c in pattern):
        return {'refusal': f"repo-grep: empty pattern, control characters, or more than {rs.RG['pattern_max_chars']} characters (config.json repo_grep.pattern_max_chars)"}
    path = _path(opt)
    if path is None: return {'refusal': 'repo-grep: --path expects a repository-relative path (no absolute path, no . or .. segment)'}
    snap = _snapshot(g)
    if not snap.git: return _failed(rs.SnapshotError('git_missing', 'git is not on PATH'), repo, sha)   # before any GitHub request
    r, why = _commit(g, repo, sha, B, extra)
    if why: return {'refusal': why}
    try:
        s = snap.ensure(repo, r['sha'])
        found = snap.grep(s, r['sha'], pattern, [path] if path else [])
    except rs.SnapshotError as e: return dict(_failed(e, repo, r['sha']), **_dated(r, repo))
    full = r['sha']
    m = [dict(cite=f"repo:{repo}/{x['path']}:{x['line']}@{full}", path=x['path'], line=x['line'], text=x['text'],
              permanent_url=sc.GH['web'] + repo + '/blob/' + full + '/' + sc.quote(x['path'], safe='/') + '#L' + str(x['line'])) for x in found['matches']]
    files = sorted({x['path'] for x in m})
    out = dict(_dated(r, repo), id=f'repo:{repo}@{full}', pattern=pattern, path=path or None, mode='fixed string, case-sensitive, binary files skipped',
               matched_lines=len(m), files_matched=len(files), truncated=found['truncated'], matches=m[:max(1, int(n))],
               results_served=min(len(m), max(1, int(n))), snapshot={k: s[k] for k in ('bytes', 'seconds', 'cached')},
               method='git fetch --depth 1 of the commit (bare, no checkout) + git grep -F', **({'skipped_paths': found['skipped_paths']} if found['skipped_paths'] else {}))
    if not m: out['note'] = 'no line holds the string at this commit' + (f' under {path}' if path else '') + ' (exact, not an index miss)'
    elif found['truncated']: out['note'] = f"more than {rs.RG['max_matches']} matching lines (config.json repo_grep.max_matches): narrow the string or --path"
    out['next'] = f'repo-file {repo}/<path>@{full} (the whole file around a line)'
    return out


def run_repo_ls(g, arg, n, opt, B, extra):
    """repo-ls <owner>/<name>[@<SHA>] [--path P]: git ls-tree -r of the commit (after the barrier); paths and sizes, submodules apart."""
    repo, sha = re.fullmatch(LS_FORM, arg).groups()
    path = _path(opt)
    if path is None: return {'refusal': 'repo-ls: --path expects a repository-relative path (no absolute path, no . or .. segment)'}
    snap = _snapshot(g)
    if not snap.git: return _failed(rs.SnapshotError('git_missing', 'git is not on PATH'), repo, sha)
    r, why = _commit(g, repo, sha, B, extra)
    if why: return {'refusal': why}
    try:
        s = snap.ensure(repo, r['sha'])
        t = snap.ls(s, r['sha'], [path] if path else [])
    except rs.SnapshotError as e: return dict(_failed(e, repo, r['sha']), **_dated(r, repo))
    cap = int(rs.RG['ls_paths_served'])
    return dict(_dated(r, repo), id=f"repo:{repo}@{r['sha']}", path=path or None, count=len(t['files']), files=t['files'][:cap],
                truncated=t['truncated'] or len(t['files']) > cap, submodules=t['submodules'], snapshot={k: s[k] for k in ('bytes', 'seconds', 'cached')},
                method='git fetch --depth 1 of the commit (bare, no checkout) + git ls-tree -r')


SOURCE = {
    'name': 'repo-grep', 'order': 47,
    'enabled_by': ('github',),                                         # plugins/code.md declares the source `github`: served with the code plugin
    'commands': {'repo-grep': {'engine': 'repo-grep', 'run': run_repo_grep, 'form': GREP_FORM, 'date_filter': False,
                               'form_msg': 'expected form <owner>/<name>[@<SHA, 7 to 40 hex>] <fixed string> [--path P] (no line break in the string)',
                               'example': 'jd/tenacity@' + '0' * 40 + ' stop_before_delay'},
                 'repo-ls': {'engine': 'repo-grep', 'run': run_repo_ls, 'form': LS_FORM, 'date_filter': False,
                             'form_msg': 'expected form <owner>/<name>[@<SHA, 7 to 40 hex>] [--path P]', 'example': 'jd/tenacity'}},
    'plugins': ('code',), 'access': 'api',
    'hosts': {sc.GH_API_HOST: {}, sc.GH_RAW_HOST: {}, sc.DEPS_DEV_HOST: {}},   # CodeClient (barrier); the git fetch goes to github_repo.web, outside CodeClient
    'terms': 'GitHub REST API for dating (GitHub Terms of Service, section H API Terms; keyless, read-only token optional, api host only) and the '
             'public git smart HTTP protocol of github.com (anonymous, one shallow fetch of one commit per call, cached)',
    'barrier': 'the commit is resolved and dated like repo-file (default branch history, repository created before T, committer date before T, '
               'backdate checks), or is the last commit of the default branch before T (repo-head); only that commit is fetched and read',
    'as_of': 'T: the content of the commit dated before T',
}
