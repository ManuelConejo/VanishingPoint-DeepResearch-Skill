# SPDX-License-Identifier: Apache-2.0
"""GitHub repository at a commit (code engine github-repo, served only when a plugin declares it): repo-info <owner>/<name>[@<SHA>] -> SPDX
licence (at the commit when a SHA is given; without a SHA also the deps.dev project: licence, Scorecard), default branch, full SHA of an abbreviated one resolved on the named repository; repo-file
[repo:]<owner>/<name>/<path>@<SHA> -> the whole file at that commit (raw host), dated by the commit. Bases in config.json github_repo; keyless
(GitHub core quota without a token), the read-only VP_GITHUB_TOKEN sent to the API host only when already resolvable (KEYS.md). Identifier
kind repo:<owner>/<name>/<path>@<SHA> (result.json; the card's `code` field). Client: code_sources.GitHubRepo over CodeClient.
A named repository without a SHA (banc code 2026-10-31, defect 1): repo-head <owner>/<name> -> the last commit of the default branch dated
before T (gated like any commit); repo-info <owner>/<name> also gives that commit (`at_T`: SHA, committer date, SPDX licence at it);
repo-tree <owner>/<name>[/<dir>]@<SHA> -> the file paths at the commit. Served with the plugin source `github` (enabled_by), or `github-repo`."""
import re
import code_sources as sc

WEB = r'(?:repo:|' + re.escape(sc.GH['web']) + r')?'                     # repo: prefix or the github.com URL of the repository
INFO_FORM = WEB + r'(' + sc.GH_REPO + r')(?:@([0-9a-f]{7,40}))?'
HEAD_FORM = WEB + r'(' + sc.GH_REPO + r')'
TREE_FORM = WEB + r'(' + sc.GH_REPO + r')(?:/(\S+?))?@([0-9a-f]{7,40})'
FILE_FORM = r'(?:repo:)?(' + sc.GH_REPO + r')/(\S+)@([0-9a-f]{7,40})'
REPO_ID_FORM = sc.GH_REPO + r'/\S+@[0-9a-f]{7,40}'                    # repo:<owner>/<name>/<path>@<SHA> (40 hex expected; shorter = warning)


def head_at_T(gh, repo, B):
    """The last commit of the default branch before T, gated (GitHubRepo.gate, then B.ok on its committer date): the resolved commit, or
    {'refusal': ...}."""
    r = gh.head_before(repo, B.T)
    if r is None: return {'refusal': f"no commit of the default branch dated before T among the {sc.GH['head_candidates']} newest listed before T (github_repo.head_candidates)"}
    why = gh.gate(r, B.T)
    if why: return {'refusal': 'after T or not datable: ' + why}
    if not B.ok(None, r.get('date')): return {'refusal': 'after T: commit dated on/after T (or undated)'}
    return r


def run_repo_head(g, arg, n, opt, B, extra):
    """repo-head <owner>/<name>: the last commit of the default branch dated before T (committer date), resolved on the named repository and
    gated like any commit (default branch history, repository created before T); then read with repo-tree / repo-file / repo-info @<SHA>."""
    repo = re.fullmatch(HEAD_FORM, arg).group(1)
    gh = sc.GitHubRepo(g.client, extra)
    r = head_at_T(gh, repo, B)
    if 'refusal' in r: return r
    return dict(r, id=f"repo:{repo}@{r['sha']}", selected='last commit of the default branch with a committer date before T',
                next=f"repo-tree {repo}@{r['sha']} | repo-file {repo}/<path>@{r['sha']} | repo-info {repo}@{r['sha']}")


def run_repo_tree(g, arg, n, opt, B, extra):
    """repo-tree <owner>/<name>[/<dir>]@<SHA>: file paths at the commit (under <dir> when given), after the same resolution and gate as repo-file."""
    repo, prefix, sha = re.fullmatch(TREE_FORM, arg).groups()
    if prefix and not sc.path_ok(prefix.rstrip('/')): return {'refusal': 'expected a repository-relative directory (no absolute path, no . or .. segment)'}
    gh = sc.GitHubRepo(g.client, extra)
    r = gh.resolve(repo, sha)
    why = gh.gate(r, B.T)
    if why: return {'refusal': 'after T or not datable: ' + why}
    if not B.ok(None, r.get('date')): return {'refusal': 'after T: commit dated on/after T (or undated)'}
    t = gh.tree(repo, r['sha'], prefix or '')
    return dict(t, id=f"repo:{repo}@{r['sha']}", repo=repo, sha=r['sha'], date=r['date'], directory=prefix or '', membership=r['membership'])


def run_repo_info(g, arg, n, opt, B, extra):
    """Without a SHA: current metadata (as_of "now", not as of T: archived, licence now, pushed_at), plus `at_T`: the last commit of the
    default branch before T (repo-head) and the SPDX licence detected at it. With a SHA: the commit resolved on the named repository, dated
    (barrier: a commit dated on/after T is refused), and the licence detected at that commit."""
    repo, sha = re.fullmatch(INFO_FORM, arg).groups()
    gh = sc.GitHubRepo(g.client, extra)
    if not sha:
        x = gh.info(repo); x['licence'] = gh.licence(repo); x['deps_dev'] = gh.project(repo)   # deps.dev: licence + Scorecard, never blocking
        try:
            h = head_at_T(gh, repo, B)
            at = h if 'refusal' in h else {'last_commit': {'sha': h['sha'], 'date': h['date'], 'id': f"repo:{repo}@{h['sha']}", 'membership': h['membership']},
                                           'licence': gh.licence(repo, h['sha'])}
        except (ValueError, RuntimeError) as e: at = {'status': 'unavailable', 'reason': str(e)}
        extra['warning'] = ('repository metadata and licence are current (as_of "now"), not as of T (archived included: GitHub gives no archiving date); '
                            '`at_T` = last commit of the default branch before T and the licence at it')
        return dict(x, as_of='now', at_T=at)
    r = gh.resolve(repo, sha)
    why = gh.gate(r, B.T)
    if why: return {'refusal': 'after T or not datable: ' + why}
    if not B.ok(None, r.get('date')): return {'refusal': 'after T: commit dated on/after T (or undated)'}
    return dict(r, licence=gh.licence(repo, r['sha']), id=f"repo:{repo}@{r['sha']}")


def run_repo_file(g, arg, n, opt, B, extra):
    """The whole file at the commit (resolved on the named repository, membership recorded); refused unless the commit is in the default branch
    history and the repository was created before T (GitHubRepo.gate); then dated by the commit (Gateway._date_filter)."""
    repo, path, sha = re.fullmatch(FILE_FORM, arg).groups()
    if not sc.path_ok(path): return {'refusal': 'expected a repository-relative path (no absolute path, no . or .. segment)'}
    gh = sc.GitHubRepo(g.client, extra)
    f = gh.file_at(repo, sha, path)
    why = gh.gate(f, B.T)
    return {'refusal': 'after T or not datable: ' + why} if why else f


SOURCE = {
    'name': 'github-repo', 'order': 46,
    'enabled_by': ('github',),                                         # plugins/code.md declares the source `github` (repository, licence, file)
    'commands': {'repo-head': {'engine': 'github-repo', 'run': run_repo_head, 'form': HEAD_FORM, 'date_filter': False,
                               'form_msg': 'expected form <owner>/<name> (the last commit of the default branch before T)', 'example': 'psf/requests'},
                 'repo-tree': {'engine': 'github-repo', 'run': run_repo_tree, 'form': TREE_FORM, 'date_filter': False,
                               'form_msg': 'expected form <owner>/<name>[/<directory>]@<SHA, 7 to 40 hex>', 'example': 'psf/requests/src@' + '0' * 40},
                 'repo-info': {'engine': 'github-repo', 'run': run_repo_info, 'form': INFO_FORM, 'date_filter': False,
                               'form_msg': 'expected form <owner>/<name>[@<SHA, 7 to 40 hex>]', 'example': 'psf/requests'},
                 'repo-file': {'engine': 'github-repo', 'run': run_repo_file, 'form': FILE_FORM,
                               'form_msg': 'expected form [repo:]<owner>/<name>/<path>@<SHA, 7 to 40 hex>', 'example': 'psf/requests/README.md@' + '0' * 40}},
    'ids': [{'prefix': 'repo', 'form': REPO_ID_FORM, 'read': False, 'card': False}],   # result.json id; on a card it is the value of the `code` field
    'plugins': ('code',), 'access': 'api',
    'hosts': {sc.GH_API_HOST: {}, sc.GH_RAW_HOST: {}, sc.DEPS_DEV_HOST: {}},                       # CodeClient: closed host list, pacing in config.json code_intervals
    'terms': 'GitHub REST API (GitHub Terms of Service, section H API Terms) and raw file host; keyless, read-only token optional (api host only)',
    'barrier': 'repo-head: last commit of the default branch with a committer date before T, then the same gate; repo-tree, repo-file and repo-info with a SHA: refused unless the commit is in the default branch history (/compare) and the repository was '
               'created before T; then dated by the commit (committer date, falsifiable in git: residual limit), a commit dated on/after T is refused; '
               'repo-info without a SHA: current metadata, marked as_of "now"',
    'as_of': 'now for repo-info without a SHA (licence and default branch observed at the call)',
}
