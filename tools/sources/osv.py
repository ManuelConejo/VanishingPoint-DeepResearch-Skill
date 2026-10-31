# SPDX-License-Identifier: Apache-2.0
"""OSV.dev vulnerabilities (code engine osv, served only when a plugin declares it): vulns <ecosystem>:<package>@<version> or
vulns commit:<40-hex SHA> (advisories whose affected ranges contain the commit), read osv:<id>."""
import re
import code_sources as sc
from sources._common import _before, extra_ok
import code_sources as sc
from sources._common import EXTRA_NO_CHAIN, RELATED_ONLY, value


def osv_item(v, B, with_details=False):
    """OSV advisory, dated by its publication: refused when `published` is absent or >= T (banc code 2026-10-31, defect 4: the barrier is
    `published`, never `modified`). An advisory published before T but modified on/after T is served whole (summary, details, ranges,
    severity, references), marked `modified_after_T` with an explicit validity note: the current record may carry post-T edits (aliases,
    fixed versions, severity); its post-T modification date is not shown. Withdrawn shown only when the withdrawal is before T."""
    vid = v.get('id')
    if not vid or not extra_ok(B, [vid, 'osv:' + vid] + list(v.get('aliases') or []), [v.get('published')], [v.get('summary')]): return None
    fresh = bool(_before(v.get('modified'), B))
    ranges = [{'package': (a.get('package') or {}).get('name'), 'ecosystem': (a.get('package') or {}).get('ecosystem'),
               'events': [e for r in a.get('ranges') or [] for e in r.get('events') or []][:20]} for a in v.get('affected') or []]
    it = {'id': 'osv:' + vid, 'osv': vid, 'aliases': v.get('aliases') or [], 'date': v.get('published'), 'date_modified': v.get('modified') if fresh else 'on/after T',
          'modified_after_T': not fresh, 'withdrawn': _before(v.get('withdrawn'), B), 'summary': v.get('summary'), 'severity': v.get('severity'),
          'affected': ranges, 'references': [r.get('url') for r in v.get('references') or []][:8], 'type': 'advisory',
          'validity': 'advisory unchanged since before T' if fresh else
                      'advisory published before T, modified on/after T: the current record is served; aliases, affected ranges, fixed versions and '
                      'severity may carry post-T edits (say so when citing them as known at T)'}
    if with_details: it['abstract'] = ' '.join(str(v.get('details') or '').split())[:6000]
    return it


OSV_COMMIT_FORM = r'commit:([0-9a-f]{40})'


def osv_vulns(client, arg, n, B):
    m = re.fullmatch(OSV_COMMIT_FORM, arg)
    if m:                                                                    # advisories whose affected ranges contain this commit
        out = [x for x in (osv_item(x, B) for x in sc.Vulns(client).query_commit(m.group(1))) if x]
        return {'commit': m.group(1), 'vulns': out[:n]}
    s, p, v = re.fullmatch(sc.OSV_FORM, arg).groups()
    vs = sc.Vulns(client).query(s, p, v)
    out = [x for x in (osv_item(x, B) for x in vs) if x]
    return {'package': p, 'version': v, 'ecosystem': sc.OSV_ECOSYSTEM[s], 'vulns': out[:n]}   # no count of today's advisories (post-T knowledge)


def read_osv(ident, client, B):
    try: v = sc.Vulns(client).get(ident)
    except ValueError as e:
        if str(e) in ('osv_id', 'provider_error:HTTP404'): return {'refusal': 'not found' if 'HTTP404' in str(e) else 'expected form osv:<OSV id>, e.g. osv:GHSA-462w-v97r-4m45'}
        raise
    return osv_item(v, B, with_details=True) or {'refusal': 'after T or forbidden'}
OSV_FORM_MSG = 'expected form <pypi|npm|cargo|go|maven|rubygems|nuget|packagist>:<package>@<version> or commit:<40-hex SHA>'


def run_vulns(g, arg, n, opt, B, extra):
    return osv_vulns(g.client, arg, n, B)                                    # barrier inside (osv_item): published < T, post-T edits marked


def read_osv_ident(ident, B, client=None):
    """osv:<id> through the code client of the gateway (Gateway.call passes it when a plugin declares osv)."""
    if client is None: return {'refusal': 'osv: identifiers are read through the code engine osv (a plugin must declare it)'}
    return read_osv(value(ident), client, B)


SOURCE = {
    'name': 'osv', 'order': 120,
    'commands': {'vulns': {'engine': 'osv', 'run': run_vulns, 'form': f'{sc.OSV_FORM}|{OSV_COMMIT_FORM}', 'form_msg': OSV_FORM_MSG, 'date_filter': False,
                          'example': 'pypi:jinja2@2.4.1'}},
    'ids': [{'prefix': 'osv', 'form': r'[A-Za-z]+-[\w.:-]+', 'export': 'software', 'export_rank': 10, 'code_engine': 'osv'}],
    'read': read_osv_ident, 'citing': EXTRA_NO_CHAIN, 'references': EXTRA_NO_CHAIN, 'related': RELATED_ONLY,
    'plugins': ('code',), 'access': 'api',
    'hosts': {'api.osv.dev': {}},                                              # CodeClient: closed host list, pacing in config.json code_intervals
    'terms': 'OSV.dev API, keyless; each advisory under the licence of its source database',
    'barrier': 'published < T; an advisory modified on/after T is served whole, marked modified_after_T (osv_item)',
}
