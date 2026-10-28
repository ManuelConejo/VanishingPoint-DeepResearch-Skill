# SPDX-License-Identifier: Apache-2.0
"""OSV.dev vulnerabilities (code engine osv, served only when a plugin declares it): vulns <ecosystem>:<package>@<version>, read osv:<id>."""
import re
import code_sources as sc
from sources._common import _before, extra_ok
import code_sources as sc
from sources._common import EXTRA_NO_CHAIN, RELATED_ONLY, value


def osv_item(v, B, with_details=False):
    """OSV advisory: refused when `published` is absent or >= T. Modified on/after T: summary, details, ranges and severity are post-T
    edits -> masked (only id, aliases, publication date kept); withdrawn shown only when the withdrawal is before T."""
    vid = v.get('id')
    if not vid or not extra_ok(B, [vid, 'osv:' + vid] + list(v.get('aliases') or []), [v.get('published')], [v.get('summary')]): return None
    fresh = bool(_before(v.get('modified'), B)); keep = (lambda x: x) if fresh else (lambda x: None)
    ranges = [{'package': (a.get('package') or {}).get('name'), 'ecosystem': (a.get('package') or {}).get('ecosystem'),
               'events': [e for r in a.get('ranges') or [] for e in r.get('events') or []][:20]} for a in v.get('affected') or []]
    it = {'id': 'osv:' + vid, 'osv': vid, 'aliases': v.get('aliases') or [], 'date': v.get('published'), 'date_modified': keep(v.get('modified')),
          'withdrawn': _before(v.get('withdrawn'), B), 'summary': keep(v.get('summary')), 'severity': keep(v.get('severity')),
          'affected': keep(ranges), 'references': keep([r.get('url') for r in v.get('references') or []][:8]), 'type': 'advisory',
          'validity': 'advisory unchanged since before T' if fresh else 'advisory modified on/after T: summary, details, ranges and severity masked; the version match uses current ranges'}
    if with_details: it['abstract'] = keep(' '.join(str(v.get('details') or '').split())[:6000]) or '(masked: advisory modified on/after T)'
    return it


def osv_vulns(client, arg, n, B):
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
OSV_FORM_MSG = 'expected form <pypi|npm|cargo|go|maven|rubygems|nuget|packagist>:<package>@<version>'


def run_vulns(g, arg, n, opt, B, extra):
    return osv_vulns(g.client, arg, n, B)                                    # barrier inside (osv_item): published < T, post-T edits masked


def read_osv_ident(ident, B, client=None):
    """osv:<id> through the code client of the gateway (Gateway.call passes it when a plugin declares osv)."""
    if client is None: return {'refusal': 'osv: identifiers are read through the code engine osv (a plugin must declare it)'}
    return read_osv(value(ident), client, B)


SOURCE = {
    'name': 'osv', 'order': 120,
    'commands': {'vulns': {'engine': 'osv', 'run': run_vulns, 'form': sc.OSV_FORM, 'form_msg': OSV_FORM_MSG, 'date_filter': False,
                          'example': 'pypi:jinja2@2.4.1'}},
    'ids': [{'prefix': 'osv', 'form': r'[A-Za-z]+-[\w.:-]+', 'export': 'software', 'export_rank': 10, 'code_engine': 'osv'}],
    'read': read_osv_ident, 'citing': EXTRA_NO_CHAIN, 'references': EXTRA_NO_CHAIN, 'related': RELATED_ONLY,
    'plugins': ('code',), 'access': 'api',
    'hosts': {'api.osv.dev': {}},                                              # CodeClient: closed host list, pacing in config.json code_intervals
    'terms': 'OSV.dev API, keyless; each advisory under the licence of its source database',
    'barrier': 'published < T; fields modified on/after T masked (osv_item)',
}
