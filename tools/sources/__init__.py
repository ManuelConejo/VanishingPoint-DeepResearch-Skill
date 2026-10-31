# SPDX-License-Identifier: Apache-2.0
"""Source registry of VanishingPoint: one source = one file in this directory (CONTRIBUTING.md, _TEMPLATE.py).

Each module `tools/sources/<name>.py` exposes SOURCE (a dict, or SOURCES, a list of dicts). Files starting with `_` are shared
helpers, never sources (_common.py: fetch with cache and pacing, Barrier, date helpers, key resolution). The registry imports
every built-in module, validates every declaration, and derives what the rest of the skill used to list by hand:
gateway engines, commands, options, host pacing, read routing and chaining; check_keys / setup_keys catalogues; validate_card /
validate_result / verifier identifier kinds; export_data types; law_checks prefixes.

User sources (opt-in): with VP_USER_SOURCES=1, every ~/.config/vp/sources/*.py is loaded too (same contract; it imports
`from sources._common import ...`). The names loaded are printed once on stderr; a directory present without the flag is
reported once on stderr and not loaded. A duplicate source name, engine, command or identifier prefix is an error (RegistryError).

Declaration (keys of SOURCE; `_TEMPLATE.py` is the commented reference):
  name, order, engines {engine: search | {'search': fn, 'options': (...)}}, commands {cmd: {engine, run, form, form_msg, example, date_filter}},
  serves (plugin source names served by this source's code engine), enabled_by (plugin source names whose declaration also enables this
  source's code engine, e.g. github -> github-repo), ids [{prefix, field, form, law_form, export, export_rank, read,
  card, code_engine}], match, read, citing / references / related (callable or "not served" message; absent = default source),
  default, plugins, access, terms, barrier, as_of, hosts {host: {interval, stop, timeout}}, key (None or key spec), wired.
"""
import importlib, importlib.util, os, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
ACCESS = ('api', 'page', 'browser', 'local', 'tos_forbidden', 'technical_block')   # ACCESS-POLICY.md; local = files of the user, no network
SEND = re.compile(r'(query:[A-Za-z_][\w-]*|bearer|header:[A-Za-z][\w-]*|oauth-client-credentials)')   # how a key may be sent
EXPORT_TYPES = ('article', 'preprint', 'paper', 'thesis', 'dataset', 'software', 'standard', 'trial', 'case', 'legislation', 'report')
WITHOUT = ('degraded', 'skipped')
CHAIN = ('citing', 'references', 'related')
USER_DIR = pathlib.Path.home() / '.config' / 'vp' / 'sources'
MISSING = object()


class RegistryError(ValueError):
    """An invalid or conflicting source declaration (duplicate name, engine, command or prefix; missing field)."""


def _err(src, msg): raise RegistryError(f"source {src.get('name') or '?'} ({src.get('_file', '?')}): {msg}")


def _norm(src, file):
    """Checked copy of one declaration with every optional field filled."""
    s = dict(src); s['_file'] = file
    if not isinstance(s.get('name'), str) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]*', s['name']): _err(s, 'name: lower-case [a-z0-9.-] required')
    s.setdefault('order', 1000); s.setdefault('wired', True); s.setdefault('default', False)
    s['engines'] = {e: (v if isinstance(v, dict) else {'search': v}) for e, v in (s.get('engines') or {}).items()}
    for e, v in s['engines'].items():
        if not callable(v.get('search')): _err(s, f'engine {e}: search callable required')
        v['options'] = tuple(v.get('options') or ())
    s['commands'] = {c: dict(v) for c, v in (s.get('commands') or {}).items()}
    for c, v in s['commands'].items():
        if not (isinstance(v.get('engine'), str) and callable(v.get('run'))): _err(s, f'command {c}: engine and run required')
        if v.get('form') and not v.get('form_msg'): _err(s, f'command {c}: form_msg required with form')
        if v.get('form') and not re.fullmatch(v['form'], v.get('example') or ''): _err(s, f'command {c}: example argument matching form required')
        v.setdefault('date_filter', True)
    s['serves'] = tuple(s.get('serves') or ())
    if s['serves'] and len({v['engine'] for v in s['commands'].values()}) != 1: _err(s, 'serves needs exactly one code engine')
    s['enabled_by'] = tuple(s.get('enabled_by') or ())
    if s['enabled_by'] and len({v['engine'] for v in s['commands'].values()}) != 1: _err(s, 'enabled_by needs exactly one code engine')
    ids = []
    for i in s.get('ids') or ():
        i = dict(i)
        if not re.fullmatch(r'[a-z][a-z0-9]*', i.get('prefix') or ''): _err(s, f"id prefix {i.get('prefix')!r}: [a-z][a-z0-9]* required")
        i.setdefault('field', i['prefix']); i.setdefault('read', True); i.setdefault('card', True)
        i.setdefault('form', None); i.setdefault('law_form', None); i.setdefault('export', None); i.setdefault('export_rank', 1000); i.setdefault('code_engine', None)
        if isinstance(i['export'], str) and i['export'] not in EXPORT_TYPES: _err(s, f"id {i['prefix']}: export {i['export']!r} not in {EXPORT_TYPES}")
        ids.append(i)
    s['ids'] = ids
    if any(i['read'] for i in ids) and not callable(s.get('read')): _err(s, 'read callable required for readable ids')
    if s.get('match') is not None and not callable(s['match']): _err(s, 'match must be callable')
    for op in CHAIN:
        if op in s and not (callable(s[op]) or isinstance(s[op], str)): _err(s, f'{op}: callable or "not served" message')
    if s['wired']:
        if s.get('access') not in ACCESS: _err(s, f'access must be one of {ACCESS}')
        if s['access'] == 'local':
            if s.get('hosts'): _err(s, 'a local source calls no host (hosts must be empty)')
        elif not s.get('hosts'): _err(s, 'hosts required (every host called, with its pacing)')
        if not (s.get('terms') and s.get('barrier')): _err(s, 'terms and barrier notes required')
        if not (s['engines'] or s['commands'] or ids): _err(s, 'a wired source declares engines, commands or ids')
    s['hosts'] = {h: dict(v or {}) for h, v in (s.get('hosts') or {}).items()}
    s['plugins'] = tuple(s.get('plugins') or ())
    k = s.get('key')
    if k is not None:
        k = dict(k); s['key'] = k
        if not k.get('vars') or not all(re.fullmatch(r'[A-Z][A-Z0-9_]*', v) for v in k['vars']): _err(s, 'key.vars: upper-case variable names required')
        k['vars'] = tuple(k['vars'])
        if not SEND.fullmatch(k.get('send') or ''): _err(s, f"key.send must match {SEND.pattern}")
        if not k.get('hosts'): _err(s, 'key.hosts required (the only hosts the key may be sent to)')
        k['hosts'] = tuple(k['hosts'])
        for f in ('url', 'free', 'reason'):
            if not k.get(f): _err(s, f'key.{f} required')
        if k.get('without') not in WITHOUT: _err(s, f'key.without must be one of {WITHOUT}')
        k.setdefault('passed', s['wired']); k.setdefault('source', s['name'])
        k.setdefault('engine', next(iter(s['engines']), None) or next((v['engine'] for v in s['commands'].values()), None) if s['wired'] else None)
        if k.get('rejected') and not k['send'].startswith('query:api_key'): _err(s, "key.rejected (generic key_invalid fallback of fetch) needs send 'query:api_key'")
    return s


def _modules_builtin():
    names = sorted(p.stem for p in HERE.glob('*.py') if not p.name.startswith('_'))
    return [importlib.import_module('sources.' + n) for n in names]


def _user_files():
    try: return sorted(p for p in USER_DIR.glob('*.py') if not p.name.startswith('_')) if USER_DIR.is_dir() else []
    except OSError: return []


def _modules_user():
    files = _user_files()
    if not files: return []
    if os.environ.get('VP_USER_SOURCES', '').strip() != '1':
        print(f'VanishingPoint: {len(files)} user source file(s) in {USER_DIR} not loaded (set VP_USER_SOURCES=1 to load them).', file=sys.stderr)
        return []
    out = []
    for f in files:
        spec = importlib.util.spec_from_file_location('sources.user_' + re.sub(r'\W', '_', f.stem), f)
        m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m
        spec.loader.exec_module(m); out.append(m)
    return out


def _declared(m):
    d = getattr(m, 'SOURCES', None) or ([m.SOURCE] if getattr(m, 'SOURCE', None) else [])
    return [_norm(x, getattr(m, '__file__', m.__name__)) for x in d]


def build(modules, user_modules=()):
    """Validated registry over the given modules (tests can build one from stubs)."""
    srcs, seen = [], {}
    for m in list(modules) + list(user_modules):
        for s in _declared(m):
            s['_user'] = m in user_modules
            srcs.append(s)
    srcs.sort(key=lambda s: (s['_user'], s['order'], s['name']))
    reg = {'sources': srcs, 'engines': {}, 'commands': {}, 'prefixes': {}, 'readable': {}, 'served_by': {}, 'default': None, 'matchers': [], 'keys': []}

    def claim(table, k, s, what):
        if k in table: _err(s, f"duplicate {what} {k!r} (already declared by {seen[(what, k)]})")
        seen[(what, k)] = s['name']; table[k] = s

    names = {}
    for s in srcs:
        claim(names, s['name'], s, 'source name')
        for e in s['engines']: claim(reg['engines'], e, s, 'engine')
        for c in s['commands']: claim(reg['commands'], c, s, 'command')
        for i in s['ids']:
            claim(reg['prefixes'], i['prefix'], s, 'identifier prefix')
            if i['read']: reg['readable'][i['prefix']] = s
        for x in s['serves']: claim(reg['served_by'], x, s, 'served name')
        if s['default']:
            if reg['default'] is not None: _err(s, f"a second default source (already {reg['default']['name']})")
            reg['default'] = s
        if s.get('match'): reg['matchers'].append(s)
        if s.get('key'): reg['keys'].append(s)
    return reg


_BUILTIN = _modules_builtin()
_USER = _modules_user()
REG = build(_BUILTIN, _USER)
SOURCES = REG['sources']                                   # ordered: built-ins by (order, name), then user sources
DEFAULT = REG['default']                                   # the source that handles identifiers no other source claims (DOI)
USER_SOURCES = [s['name'] for s in SOURCES if s['_user']]
if USER_SOURCES: print('VanishingPoint: user sources loaded from ' + str(USER_DIR) + ': ' + ', '.join(USER_SOURCES), file=sys.stderr)
_HELPERS = [importlib.import_module('sources.' + p.stem) for p in sorted(HERE.glob('_*.py')) if p.stem not in ('__init__', '_TEMPLATE')]
MODULES = _HELPERS + _BUILTIN + _USER                      # every module whose globals may hold a shared helper (rebind)

# ---- derived tables (the only lists of sources in the skill)
ENGINES = {e: v['search'] for s in SOURCES for e, v in s['engines'].items()}                         # engine -> search(q, n, B, **opts)
FILTER_OPT = {'search-' + e: v['options'] for s in SOURCES for e, v in s['engines'].items() if v['options']}
CODE_COMMANDS = {c: v for s in SOURCES for c, v in s['commands'].items()}                            # code command -> spec
CODE_ENGINES = {c: v['engine'] for c, v in CODE_COMMANDS.items()}                                    # code command -> engine name
SERVED_BY = {x: next(iter(s['commands'].values()))['engine'] for s in SOURCES for x in s['serves']}  # plugin source name -> code engine
ENABLED_BY = {}                                                                                      # plugin source name -> code engines it also enables
for _s in SOURCES:
    for _x in _s['enabled_by']: ENABLED_BY.setdefault(_x, ()); ENABLED_BY[_x] += (next(iter(_s['commands'].values()))['engine'],)
IDS = [dict(i, source=s['name']) for s in SOURCES for i in s['ids']]                                 # identifier kinds, registry order


def apply_hosts(common):
    """Host pacing, stop codes, timeouts and key rules of every source into the shared tables of _common (fetch reads them).
    Two sources giving the same host different settings = RegistryError."""
    who = {}
    for s in SOURCES:
        for h, v in s['hosts'].items():
            for k, x in v.items():
                if (h, k) in who and who[(h, k)][1] != x: _err(s, f'host {h}: {k}={x!r} differs from {who[(h, k)][0]} ({who[(h, k)][1]!r})')
                who[(h, k)] = (s['name'], x)
            if 'interval' in v: common.INTERVAL[h] = v['interval']
            if 'stop' in v: common.STOP[h] = tuple(v['stop'])
            if 'timeout' in v: common.TIMEOUT[h] = v['timeout']
        k = s.get('key')
        if not k: continue
        for h, sec in (k.get('interval_with_key') or {}).items(): common.KEY_INTERVAL[h] = (k['vars'][0], sec)
        if k.get('rejected'):
            for h in k['hosts']: common.KEY_REJECTED[h] = (k['vars'][0], tuple(k['rejected']['codes']), tuple(k['rejected']['markers']))


def owner(ident):
    """The source that serves this identifier: its prefix's source, else a source whose match() claims it, else DEFAULT."""
    s = ident.strip(); p = s.split(':', 1)[0].lower() if ':' in s else None
    o = REG['readable'].get(p)
    if o is not None and not o['default']: return o
    for m in REG['matchers']:
        if m['match'](s): return m
    return o or DEFAULT


def id_spec(ident):
    """The declared identifier kind of `prefix:value` (by prefix only), else None."""
    s = ident.strip(); p = s.split(':', 1)[0].lower() if ':' in s else None
    o = REG['readable'].get(p)
    return next(i for i in o['ids'] if i['prefix'] == p) if o else None


def rebind(name, old, new):
    """`gateway.<name> = new` also replaces `name` in every helper/source module holding the same object `old` (fetch, STATE...)."""
    for m in MODULES:
        if m.__dict__.get(name, MISSING) is old: setattr(m, name, new)


def public(skip=('SOURCE', 'SOURCES', 'check_key')):
    """name -> object of every helper/source module (first definition wins): gateway re-exports them (gateway.search_pubmed...)."""
    out = {}
    for m in MODULES:
        for k, v in vars(m).items():
            if k.startswith('__') or k in skip or type(v) is type(sys): continue
            out.setdefault(k, v)
    return out


def key_specs():
    """Ordered [(source, key spec)]: every declared key (catalogue of check_keys and setup_keys)."""
    return [(s, s['key']) for s in REG['keys']]


apply_hosts(importlib.import_module('sources._common'))
