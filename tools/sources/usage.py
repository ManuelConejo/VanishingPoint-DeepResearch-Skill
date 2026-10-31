# SPDX-License-Identifier: Apache-2.0
"""ecosyste.ms package usage (code engine ecosyste.ms, command usage <registry>:<package>, or usage repo:<owner>/<name> for a GitHub
repository: licence, pushed_at, archived): counts observed now (as_of "now")."""
import re
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
    x = sc.Usage(g.client).lookup(m.group(1), m.group(2), B.T.isoformat())
    rel = [v for v in x.pop('releases_before_T') if B.ok(None, v.get('date'))]          # undated, on/after T: removed and counted
    if not rel: B.excluded += 1; return {'refusal': 'no release published before T (package absent at T or undatable)'}
    first = x.get('first_release_date')
    x.update(latest_release_before_T=rel[0], first_release_date=first if first and B.ok(None, first) else None, date=rel[0]['date'], as_of='now', as_of_note='counts, maintainers, licences: observed now (date of the call), not as of T; only release dates are bounded by T')
    extra['warning'] = 'usage counts are current (as_of "now"), not as of T'
    return x


SOURCE = {
    'name': 'ecosyste.ms', 'order': 125,
    'commands': {'usage': {'engine': 'ecosyste.ms', 'run': code_usage, 'date_filter': False, 'example': 'pypi:requests'}},
    'plugins': ('code',), 'access': 'api',
    'hosts': {h: {} for h in sorted(sc.USAGE_HOSTS)},                                    # CodeClient (sc.USAGE_HOSTS), pacing in config.json code_intervals
    'terms': 'ecosyste.ms packages API, keyless',
    'barrier': 'a release published before T required (provider filter published_before, then local check); latest release served = latest before T',
    'as_of': 'now: counts, maintainers and licences are observed at the call, not as of T (marked on every record)',
}
