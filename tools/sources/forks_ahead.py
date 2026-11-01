"""Forks with work of their own before T (code engine forks-ahead, served with plugins/code.md through enabled_by: github):
forks-ahead <owner>/<name> -> the most active forks (GitHub forks API, sort and bounds in config.json forks_ahead) that hold commits of their
own before T: for each, the fork head at T (last commit of its default branch with a committer date before T), the GitHub compare
<upstream head at T>...<fork head at T> (commits ahead, each dated before T; files touched; messages), cited repo:<fork>@<SHA40>. Forks
without a commit of their own (behind, identical, merges only, never pushed after creation) are excluded and counted. The upstream head
at T passes the repo-head barrier; the fork head passes GitHubRepo.backdate (signals that it entered the fork on/after T), and every commit
ahead gets the dates check. Keyless (GitHub core quota), the read-only VP_GITHUB_TOKEN sent to the API host only when the key rule resolves
it; a rate limit stops the tool, typed, with the forks already compared. Client: code_sources.GitHubRepo."""
import re
from urllib.parse import urlencode
import code_sources as sc
from sources._common import CFG, _before

FA = CFG['forks_ahead']
FORM = r'(?:repo:|' + re.escape(sc.GH['web']) + r')?(' + sc.GH_REPO + r')/?'
SHA40 = re.compile(r'[0-9a-f]{40}')


def _checks():
    return sc.GH['backdate_checks'] if FA.get('backdate_checks') is None else FA['backdate_checks']


def fork_head(gh, fork, branch, B):
    """Last commit of the fork's default branch with a committer date before T (GET /commits?sha=<branch>&until=T, newest first):
    {'sha', 'date', 'author_date', 'parents', 'default_branch'} or None. The list item carries the dates and parents: no further request."""
    d = gh._api('repos/' + gh.check(fork) + '/commits?' + urlencode({'sha': branch, 'until': B.T.isoformat() + 'T00:00:00Z', 'per_page': int(sc.GH['head_candidates'])}))
    for c in d if isinstance(d, list) else []:
        if not isinstance(c, dict): continue
        sha, cm = str(c.get('sha') or ''), c.get('commit') or {}
        date = str((cm.get('committer') or {}).get('date') or '')
        if SHA40.fullmatch(sha) and re.match(r'\d{4}-\d{2}-\d{2}', date) and _before(date, B):
            return {'sha': sha, 'date': date, 'author_date': (cm.get('author') or {}).get('date'), 'default_branch': branch,
                    'parents': [str(p.get('sha')) for p in c.get('parents') or [] if isinstance(p, dict) and SHA40.fullmatch(str(p.get('sha') or ''))]}
    return None


def compare(gh, repo, fork, base, head, B):
    """GET /repos/<repo>/compare/<base>...<fork owner>:<head>: (served dict, exclusion reason or None). Commits ahead must all be dated before T
    (a commit reachable from a head dated before T but dated on/after T = backdated history: the fork is refused)."""
    owner = fork.split('/')[0]
    d = gh._api('repos/' + gh.check(repo) + '/compare/' + base + '...' + owner + ':' + head)
    st = d.get('status')
    commits = [c for c in d.get('commits') or [] if isinstance(c, dict) and SHA40.fullmatch(str(c.get('sha') or ''))]
    if st not in ('ahead', 'diverged') or not commits: return None, f'no commit of its own before T (compare status {sc.meta(st)})'
    ahead = d.get('ahead_by')
    if not isinstance(ahead, int) or ahead > len(commits):              # Codex review 2026-10-31, item 7: an unlisted commit is undated, and the
        return None, (f'GitHub listed {len(commits)} of {sc.meta(ahead)} commits ahead: the others cannot be dated, and the files touched cover '   # files cover them too
                      'them too (comparison incomplete, refused)')
    late = [c['sha'][:12] for c in commits if not _before(((c.get('commit') or {}).get('committer') or {}).get('date'), B)]
    if late: return None, f'commits ahead dated on/after T reachable from the head before T (backdated history): {", ".join(late[:5])}'
    rows = []
    for c in commits:
        cm = c.get('commit') or {}
        r = {'sha': c['sha'], 'date': (cm.get('committer') or {}).get('date'), 'author_date': (cm.get('author') or {}).get('date')}
        bd = gh.backdate(fork, r, B.T, only=['dates'])                       # no request: committer date earlier than the author date
        rows.append(dict(r, id=f"repo:{fork}@{c['sha']}", merge=len(c.get('parents') or []) > 1,
                         message=sc.meta(str(cm.get('message') or ''))[:int(FA['message_chars'])] if cm.get('message') else '',
                         **({'suspect': bd['signals'][0]['evidence']} if bd['verdict'] == 'suspect' else {})))
    own = [r for r in rows if not r['merge']]
    if not own: return None, 'only merge commits ahead (no commit of its own before T)'
    files = [f for f in d.get('files') or [] if isinstance(f, dict) and sc.path_ok(str(f.get('filename') or ''))]
    rows.sort(key=lambda r: str(r['date']), reverse=True)
    return {'status': st, 'ahead_by': d.get('ahead_by'), 'behind_by': d.get('behind_by'), 'own_commits': len(own), 'merge_commits': len(rows) - len(own),
            'commits': rows[:int(FA['commits_served'])], 'commits_listed': len(rows),
            'files': [{'path': sc.meta(f['filename']), 'status': sc.meta(f.get('status')), 'additions': f.get('additions'), 'deletions': f.get('deletions')}
                      for f in files[:int(FA['files_served'])]], 'files_touched': len(files),
            'compare_url': sc.GH['web'] + repo + '/compare/' + base + '...' + owner + ':' + head}, None


def run_forks_ahead(g, arg, n, opt, B, extra):
    repo = sc.GitHubRepo.check(re.fullmatch(FORM, arg.strip()).group(1))
    gh = sc.GitHubRepo(g.client, extra)
    try: tok = sc.read_token()
    except ValueError: tok = None
    bound = int(FA['forks_compared_with_token'] if tok else FA['forks_compared'])
    base, why = gh.head_gated(repo, B)
    if why: return {'refusal': 'forks-ahead: upstream head at T not established: ' + why}
    d = gh._api('repos/' + repo + '/forks?' + urlencode({'sort': FA['forks_sort'], 'per_page': int(FA['forks_listed'])}))
    listed = [f for f in d if isinstance(f, dict)] if isinstance(d, list) else []
    excluded, cands = {'created_on_or_after_T': 0, 'never_pushed_after_creation': 0}, []
    for f in listed:
        name = sc.repo_name(f.get('full_name'), None)
        if not name: continue
        if not _before(f.get('created_at'), B): excluded['created_on_or_after_T'] += 1; continue
        if not str(f.get('pushed_at') or '') > str(f.get('created_at') or ''): excluded['never_pushed_after_creation'] += 1; continue
        cands.append((name, f))
    out, dropped, stopped = [], [], None
    for name, f in cands[:bound]:
        try:
            br = sc.meta(f.get('default_branch'))
            h = fork_head(gh, name, br, B) if br else None
            if h is None: dropped.append({'fork': name, 'reason': 'no commit of its default branch dated before T among the newest listed'}); continue
            if h['sha'] == base['sha']: dropped.append({'fork': name, 'reason': 'head at T identical to the upstream head at T'}); continue
            cmp_, why = compare(gh, repo, name, base['sha'], h['sha'], B)
            if why: dropped.append({'fork': name, 'reason': why}); continue
            bd = gh.backdate(name, h, B.T, only=_checks())
            if bd['verdict'] == 'entered_after_T':
                dropped.append({'fork': name, 'reason': 'head entered the fork on/after T: ' + '; '.join(x['evidence'] for x in bd['signals'] if x['strength'] == 'definitive')}); continue
            out.append({'fork': name, 'id': f"repo:{name}@{h['sha']}", 'url': sc.GH['web'] + name, 'created_at': f.get('created_at'),
                        'head_at_T': {'sha': h['sha'], 'date': h['date'], 'branch': br, 'id': f"repo:{name}@{h['sha']}"}, 'date': h['date'],
                        'popularity': {'stars': f.get('stargazers_count'), 'pushed_at': sc.meta(f.get('pushed_at')), 'as_of': 'now'},
                        **cmp_, 'backdate_check': bd})
        except ValueError as e:
            if str(e) == 'rate_limited': stopped = 'rate_limited: GitHub API quota exhausted, stopped (no retry, no circumvention); forks after this one not compared'; break
            dropped.append({'fork': name, 'reason': f'not compared ({e})'})
        except RuntimeError as e: dropped.append({'fork': name, 'reason': f'not compared ({e})'})
    out.sort(key=lambda x: -x['own_commits'])                                  # stable: server order among equals
    res = {'repo': repo, 'upstream_head_at_T': {'sha': base['sha'], 'date': base['date'], 'id': f"repo:{repo}@{base['sha']}",
                                                'backdate_check': (base.get('backdate_check') or {}).get('verdict')},
           'forks': out[:max(1, int(n))], 'forks_with_own_commits': len(out),
           'scanned': {'listed': len(listed), 'sort': FA['forks_sort'], 'candidates': len(cands), 'compared_bound': bound, 'compared': len(out) + len(dropped),
                       'excluded_without_request': excluded, 'excluded_after_compare': dropped},
           'rule': 'own commits = commits of the fork head at T not in the upstream head at T (compare), each dated before T, merges not counted; '
                   'files and messages are those of these commits only (no patch served)',
           'residual': 'stars and pushed_at are observed now; a commit ahead may come from another upstream branch merged into the fork; committer dates '
                       'are set by git (backdate_check: signals only)'}
    if stopped: res['stopped'] = stopped
    return res


SOURCE = {
    'name': 'forks-ahead', 'order': 49,
    'enabled_by': ('github',),                                         # plugins/code.md declares `github`: served with the code plugin
    'commands': {'forks-ahead': {'engine': 'forks-ahead', 'run': run_forks_ahead, 'form': FORM, 'date_filter': False,
                                 'form_msg': 'expected form <owner>/<name> (the upstream repository whose forks are compared)', 'example': 'urllib3/urllib3'}},
    'plugins': ('code',), 'access': 'api',
    'hosts': {sc.GH_API_HOST: {}},                                           # CodeClient: closed host list, pacing in config.json code_intervals
    'terms': 'GitHub REST API (GitHub Terms of Service, section H API Terms); keyless, read-only token optional (api host only)',
    'barrier': 'upstream head at T as repo-head (gate, committer date before T, backdate signals); fork created before T; fork head = last commit of its '
               'default branch with a committer date before T, refused when the backdate checks show it entered on/after T; every commit ahead dated '
               'before T (else the fork is refused); stars and pushed_at observed now',
    'as_of': 'now for stars and pushed_at of the forks',
}
