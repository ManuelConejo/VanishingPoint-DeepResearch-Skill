# SPDX-License-Identifier: Apache-2.0
"""ecosyste.ms package usage (code engine ecosyste.ms, command usage <registry>:<package>, or usage repo:<owner>/<name> for a GitHub
repository: licence, pushed_at, archived): counts observed now (as_of "now"). A package also gets: the highest version published before T
beside the latest by date (pre-releases marked), the names of its dependent packages released before T (one bounded request, config usage;
dependency at T not established), and repo_mismatch when its repository is not the one expected (--repo, else capsule.json Y.repo)."""
import json, pathlib, re
import code_sources as sc

REPO_FORM = r'repo:(' + sc.GH_REPO + r')'                                # usage repo:<owner>/<name>: GitHub repository lookup


def code_usage(g, arg, n, opt, B, extra):
    """ecosyste.ms package usage. Counts and maintainers are observed NOW (as_of "now"), never as of T; the package must have a release
    published before T; the latest release served is the latest one before T (provider filter published_before, then local check)."""
    r = re.fullmatch(REPO_FORM, arg.strip())
    if r:                                                                    # repository lookup (repos.ecosyste.ms): created before T, observed now
        x = sc.Usage(g.client).repository(r.group(1))
        if not B.ok(None, x.get('created_at')): return {'refusal': 'repository created on/after T (or undated)'}
        extra['warning'] = 'repository metadata are current (as_of "now"), not as of T'
        return dict(x, date=x.get('created_at'), as_of='now', as_of_note='licence, pushed_at, archived, stars: observed now; only created_at is bounded by T')
    m = re.fullmatch(sc.USAGE_FORM, arg)
    if not m: return {'refusal': sc.USAGE_FORM_MSG + ' or repo:<owner>/<name>'}
    u = sc.Usage(g.client)
    x = u.lookup(m.group(1), m.group(2), B.T.isoformat())
    rel = [v for v in x.pop('releases_before_T') if B.ok(None, v.get('date'))]          # undated, on/after T: removed and counted
    if not rel: B.excluded += 1; return {'refusal': 'no release published before T (package absent at T or undatable)'}
    first = x.get('first_release_date')
    stable = [v for v in rel if not v['prerelease'] and sc.version_key(v['number'])]
    high = max(stable or [v for v in rel if sc.version_key(v['number'])] or [rel[0]], key=lambda v: sc.version_key(v['number']) or ())
    x.update(latest_release_before_T=rel[0], highest_release_before_T=dict(high, note='highest version number published before T' + ('' if stable else ' (no stable release)')),
             first_release_date=first if first and B.ok(None, first) else None, date=rel[0]['date'], as_of='now',
             as_of_note='counts, maintainers, licences, dependents: observed now (date of the call), not as of T; only release dates are bounded by T')
    if high['number'] != rel[0]['number']:
        x['latest_note'] = 'the latest release before T by date is not the highest version (a backport or a pre-release published later): both are served'
    want = expected_repo(g, opt)                                                          # paquet homonyme: the package's repository vs Y
    got = sc.github_repo_of(str(x.get('repository_url') or '').strip().rstrip('/').removesuffix('.git'))
    if want:
        x['expected_repository'] = want
        x['repo_mismatch'] = None if not got else got.lower() != want.lower()
        if x['repo_mismatch']: x['repo_mismatch_note'] = f'the package {m.group(2)} points to {got}, not to {want}: a namesake package, its usage says nothing about {want}'
        elif got is None: x['repo_mismatch_note'] = 'the package names no GitHub repository: its link to ' + want + ' is not established'
    try: deps = u.dependents(m.group(1), m.group(2))
    except (ValueError, RuntimeError) as e: x['dependents'] = {'status': 'unavailable', 'reason': str(e)}
    else:
        kept = [d for d in deps if B.ok(None, d.get('first_release_date'))]
        x['dependents'] = {'status': 'ok', 'read': len(deps), 'first_release_before_T': len(kept), 'excluded_after_T_or_undated': len(deps) - len(kept),
                           'packages': kept[:int(sc.USAGE['dependents_served'])], 'sort': sc.USAGE['dependents_sort'] + ' desc (observed now)',
                           'caution': 'dependency at T not established (ecosyste.ms gives the current dependency); a package dependent is context, '
                                      'not a second use of the mechanism: read its code (repo-file) before any claim'}
    extra['warning'] = 'usage counts and dependents are current (as_of "now"), not as of T'
    return x


def expected_repo(g, opt):
    """The repository the package should belong to: --repo <owner>/<name>, else Y.repo of capsule.json next to the state directory; else None."""
    r = str((opt or {}).get('repo') or '').strip()
    if re.fullmatch(sc.GH_REPO, r): return r
    try: y = json.loads((pathlib.Path(g.state).parent / 'capsule.json').read_text()).get('Y')
    except (OSError, ValueError, AttributeError, TypeError): return None
    v = re.sub(r'^(?:https?://)?github\.com/', '', str((y or {}).get('repo') or '') if isinstance(y, dict) else '').rstrip('/').removesuffix('.git')
    return v if re.fullmatch(sc.GH_REPO, v) else None


SOURCE = {
    'name': 'ecosyste.ms', 'order': 125,
    'commands': {'usage': {'engine': 'ecosyste.ms', 'run': code_usage, 'date_filter': False, 'example': 'pypi:requests'}},
    'plugins': ('code',), 'access': 'api',
    'hosts': {h: {} for h in sorted(sc.USAGE_HOSTS)},                                    # CodeClient (sc.USAGE_HOSTS), pacing in config.json code_intervals
    'terms': 'ecosyste.ms packages API, keyless',
    'barrier': 'a release published before T required (provider filter published_before, then local check); latest release served = latest before T',
    'as_of': 'now: counts, maintainers and licences are observed at the call, not as of T (marked on every record)',
}
