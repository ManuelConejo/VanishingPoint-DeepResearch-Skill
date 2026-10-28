# SPDX-License-Identifier: Apache-2.0
"""Package versions (code engine `versions`, plugins/code.md): versions <pypi|npm|cargo>:<package>@<version> -> registry metadata and the
deps.dev dependency graph and advisories. Client: code_sources.CodeClient."""
import re
import code_sources as sc

VERSION_FORM = r'(pypi|npm|cargo):(@?[A-Za-z0-9][\w.+-]*(?:/[A-Za-z0-9][\w.+-]*)?)@([A-Za-z0-9][\w.+-]*)'          # package (npm @scope/name allowed) @ version
VERSION_FORM_MSG = 'expected form <pypi|npm|cargo>:<package>@<version>'


def run_versions(g, arg, n, opt, B, extra):
    s, p, v = re.fullmatch(VERSION_FORM, arg).groups(); vs = sc.Versions(g.client)
    m, d = vs.metadata(s, p, v), vs.deps(s, p, v)                       # date = publishedAt of deps.dev, else the registry date
    return dict(m, date=d['date'] or m['date'], date_registry=m['date'], date_deps_dev=d['date'], graph=d['dependencies'], edges=d['edges'], advisories=d['advisories'])


SOURCE = {
    'name': 'versions', 'order': 45,
    'commands': {'versions': {'engine': 'versions', 'run': run_versions, 'form': VERSION_FORM, 'form_msg': VERSION_FORM_MSG,
                             'example': 'pypi:requests@2.31.0'}},
    'serves': ('deps.dev', 'pypi', 'npm', 'crates'),
    'plugins': ('code',), 'access': 'api',
    'hosts': {'api.deps.dev': {}, 'pypi.org': {}, 'registry.npmjs.org': {}, 'crates.io': {}},
    'terms': 'deps.dev API (Google), PyPI JSON API, npm registry, crates.io API (crawler policy: identified user agent): keyless',
    'barrier': 'the version is dated by deps.dev publishedAt, else the registry date; a version dated >= T is refused (Gateway._date_filter)',
}
