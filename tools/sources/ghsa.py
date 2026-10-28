# SPDX-License-Identifier: Apache-2.0
"""GitHub Advisory Database (code engine github-advisory, served only when a plugin declares it): advisories <ecosystem>:<package>[@<version>]
lists the GitHub security advisories published before T (GitHub REST "global advisories", server filter published = [start, eve of T]);
read ghsa:<GHSA id>. Transport: code_sources.CodeClient (HTTPS, closed host list, no redirect, 5 MB cap, receipts without URL nor token,
api.github.com pacing of config code_intervals). The read-only VP_GITHUB_TOKEN is sent (Bearer, api.github.com only) when present; without
it the API is called anonymously (60 requests/h). A token GitHub rejects (401) is remembered as invalid and the call is repeated without it."""
import re
from urllib.parse import quote, urlencode
import code_sources as sc
from sources._common import CFG, _before, extra_ok, value

API = 'https://api.github.com/advisories'
ECOSYSTEM = {'pypi': 'pip', 'npm': 'npm', 'cargo': 'rust', 'go': 'go', 'maven': 'maven', 'rubygems': 'rubygems', 'nuget': 'nuget',
             'packagist': 'composer', 'pub': 'pub', 'hex': 'erlang', 'swift': 'swift', 'actions': 'actions'}
FORM = r'(' + '|'.join(ECOSYSTEM) + r'):(@?[A-Za-z0-9][\w.+\-/:]{0,200}?)(?:@([A-Za-z0-9][\w.+\-]{0,100}))?'
FORM_MSG = 'expected form <' + '|'.join(ECOSYSTEM) + '>:<package>[@<version>], e.g. pypi:jinja2@2.4.1'
GHSA_ID = r'GHSA(-[23456789cfghjmpqrvwx]{4}){3}'
NO_CHAIN = 'citation chaining not served for ghsa: identifiers (advisories)'
TYPES = str(CFG['linked_sources']['ghsa_types'])


def ghsa_item(v, B, with_details=False):
    """GHSA advisory: refused when `published_at` is absent or >= T. Updated on/after T: summary, description, affected ranges, severity,
    CVSS, CWEs and references are post-T edits -> masked (id, aliases and publication date kept); review, NVD and withdrawal dates shown
    only when before T; EPSS (a current score) never served."""
    gid = v.get('ghsa_id')
    aliases = [i.get('value') for i in v.get('identifiers') or [] if i.get('value') and i.get('value') != gid]
    if not gid or not extra_ok(B, [gid, 'ghsa:' + gid, 'osv:' + gid] + aliases, [v.get('published_at')], [v.get('summary')]): return None
    fresh = bool(_before(v.get('updated_at'), B)); keep = (lambda x: x) if fresh else (lambda x: None)
    affected = [{'package': (a.get('package') or {}).get('name'), 'ecosystem': (a.get('package') or {}).get('ecosystem'),
                 'vulnerable_version_range': a.get('vulnerable_version_range'), 'first_patched_version': a.get('first_patched_version')}
                for a in v.get('vulnerabilities') or []]
    it = {'id': 'ghsa:' + gid, 'ghsa': gid, 'aliases': aliases, 'date': v.get('published_at'), 'date_updated': keep(v.get('updated_at')),
          'github_reviewed_at': _before(v.get('github_reviewed_at'), B), 'nvd_published_at': _before(v.get('nvd_published_at'), B),
          'withdrawn': _before(v.get('withdrawn_at'), B), 'advisory_type': v.get('type'), 'summary': keep(v.get('summary')),
          'severity': keep(v.get('severity')), 'cvss': keep((v.get('cvss') or {}).get('vector_string')), 'cwes': keep([c.get('cwe_id') for c in v.get('cwes') or []]),
          'affected': keep(affected[:20]), 'references': keep(list(v.get('references') or [])[:8]), 'url': v.get('html_url'), 'type': 'advisory',
          'validity': 'advisory unchanged since before T' if fresh else 'advisory updated on/after T: summary, description, ranges, severity and references masked; the version match uses current ranges'}
    if with_details: it['abstract'] = keep(' '.join(str(v.get('description') or '').split())[:6000]) or '(masked: advisory updated on/after T)'
    return it


def _get(client, url, extra):
    """JSON through the code client: with the token when present and not rejected, else anonymous; 401 with the token -> marked invalid,
    one anonymous retry. The token value never leaves CodeClient.get (receipts carry no URL and no header)."""
    try: tok = sc.read_token()
    except ValueError: tok = None; extra['github_token'] = 'credential_invalid (not sent)'
    if tok and 'VP_GITHUB_TOKEN' in sc.invalid_keys(client.cache_dir): tok = None
    if tok:
        try: return client.json(url, tok)
        except ValueError as e:
            if str(e) != 'provider_error:HTTP401': raise
            sc.mark_invalid(client.cache_dir, 'VP_GITHUB_TOKEN'); extra['key_invalid_github'] = 'VP_GITHUB_TOKEN rejected (401): anonymous retry'
    else: extra.setdefault('github_token', 'absent: anonymous (60 requests/h)')
    return client.json(url)


def run_advisories(g, arg, n, opt, B, extra):
    eco, pkg, ver = re.fullmatch(FORM, arg).groups()
    q = {'ecosystem': ECOSYSTEM[eco], 'affects': pkg + ('@' + ver if ver else ''), 'published': f'{B.start}..{B.eve}', 'type': TYPES,
         'sort': 'published', 'direction': 'desc', 'per_page': min(n, 100)}
    rows = _get(g.client, API + '?' + urlencode(q), extra)
    out = [x for x in (ghsa_item(v, B) for v in rows if isinstance(v, dict)) if x] if isinstance(rows, list) else []
    return {'package': pkg, 'version': ver, 'ecosystem': ECOSYSTEM[eco], 'advisories': out[:n]}   # no count of today's advisories


def read_ghsa_ident(ident, B, client=None):
    """ghsa:<GHSA id> through the code client of the gateway (Gateway.call passes it when a plugin declares github-advisory)."""
    if client is None: return {'refusal': 'ghsa: identifiers are read through the code engine github-advisory (a plugin must declare it)'}
    gid = value(ident)
    if not re.fullmatch(GHSA_ID, gid): return {'refusal': 'expected form ghsa:GHSA-xxxx-xxxx-xxxx'}
    try: v = _get(client, API + '/' + quote(gid, safe=''), {})
    except ValueError as e:
        if str(e) == 'provider_error:HTTP404': return {'refusal': 'not found'}
        raise
    return ghsa_item(v, B, with_details=True) or {'refusal': 'after T or forbidden'}


SOURCE = {
    'name': 'github-advisory', 'order': 122,
    'commands': {'advisories': {'engine': 'github-advisory', 'run': run_advisories, 'form': FORM, 'form_msg': FORM_MSG, 'date_filter': False,
                                'example': 'pypi:jinja2@2.4.1'}},
    'ids': [{'prefix': 'ghsa', 'form': r'GHSA(-[23456789cfghjmpqrvwx]{4}){3}', 'export': 'software', 'export_rank': 12, 'code_engine': 'github-advisory'}],
    'read': read_ghsa_ident, 'citing': NO_CHAIN, 'references': NO_CHAIN, 'related': NO_CHAIN,
    'plugins': ('code',), 'access': 'api',
    'hosts': {'api.github.com': {}},                                          # CodeClient: closed host list, pacing in config.json code_intervals
    'terms': 'GitHub REST API (GitHub Terms of Service, section H API Terms; Acceptable Use Policies 7: research use of public non-personal '
             'information when the resulting publications are open access); GitHub Advisory Database data CC-BY 4.0',
    'barrier': 'provider side: published = [start, eve of T]; local: published_at < T; fields updated on/after T masked (ghsa_item); '
               'review, NVD and withdrawal dates only when before T; EPSS never served',
}
