#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Dated gateway of VanishingPoint (non-leak measured on our benches: 19/19 cases).
The only document access of the engine. Refuses every document dated >= T (publication AND indexing when available),
the forbidden DOIs and titles, and the engines that no plugin declared.

Command line:
  gateway.py [--plugin P.md ...] [--T YYYY-MM-DD | --case ID] [--run NAME] [--state DIR] [--cap N] [--since YEAR]
             <command> <argument> [--n N]
  --plugin takes a path from the current directory, a path from the skill directory (plugins/cs-ai.md) or a bare name (cs-ai): the gateway
  runs the same from any directory; an unknown plugin stops with exit 2 and the list of the plugins shipped.
  Call pools: the searches count in `counter-<run>.txt` (cap: --cap, else the plugins' `cap:`, else config call_cap.default); tools/verifier.py
  opens the pool `verifier` (`counter-<run>.verifier.txt`, cap: config verifier.call_cap), so verification never competes with the searches.
  commands: sources | search-<engine> "<query>" | read <id> | citing <id> | references <id> | related <id> (OpenAlex related works, same barrier)
  wired engines: pubmed, europepmc, crossref, openalex, arxiv   (id: pmid:NNN | doi:10.x | arxiv:2501.01234)
  law engines (plugins/law.md): eurlex, justice-administrative [--court CE|TA75|CAA69] [--from YYYY-MM-DD] [--to YYYY-MM-DD], hal, theses-fr
    (id: celex:32016R0679 | ecli:ECLI:EU:... | ecli:ECLI:FR:... | ja:<court>/<file> | hal:hal-0123 | thesesfr:<nnt>)
  code engines (code_sources.py; served only when a plugin declares them): search-code "<pattern>" [--language L] [--repo owner/repo] |
    versions <pypi|npm|cargo>:<package>@<version> | paper-code <arxiv> | provenance <origin https://... | swh:1:...>
  extra keyless engines: clinicaltrials (biology), dblp (cs-ai), econbiz (finance)   (id: nct:NCT01234567 | dblp:conf/acl/Xiong0LZ24 | econbiz:10011386660);
    code engine osv: vulns <pypi|npm|cargo|go|maven|rubygems|nuget|packagist>:<package>@<version> ; read osv:<id>
  preprint engines (plugins/biology.md): biorxiv, medrxiv (Europe PMC words, versions dated on api.biorxiv.org; id doi:<preprint DOI>; read biorxiv:<DOI> | medrxiv:<DOI>)
  CS engines (plugins/cs-ai.md, v0.4.6): hf-models, hf-datasets (read hfmodel:<owner/name> | hfdataset:<owner/name>: card at the last commit before T),
    standards (rfc:<n> | pep:<n> | w3c:<shortname>), proceedings (acl:<Anthology id> | pmlr:v<vol>/<key> | cvf:content/<CONF>/html/<name>_paper)
  PISTE engines (plugins/law.md, credentials PISTE_CLIENT_ID + PISTE_CLIENT_SECRET, else skipped with 0 request): judilibre [--court cc|ca|tj|tcom]
    [--chamber civ1|soc|cr...] [--from] [--to], legifrance [--fund code|loda|jorf] (read judilibre:<id> | legi:LEGIARTI.../LEGITEXT... | jorf:JORFTEXT...)
  AI engines (plugins/cs-ai.md): openreview, zenodo, hal-info (id: openreview:<forum id> | zenodo:<record id>); code engine usage <pypi|npm|cargo|...>:<package> (ecosyste.ms)
  finance data engines (plugins/finance.md, v0.4.9): dbnomics (keyless; current values marked as_of "now"; read dbnomics:<provider>/<dataset>/<series>),
    fred (FRED_API_KEY, else skipped with 0 request; ALFRED vintage of the eve of T; read fred:<series id>); observations kept only when their period ends before T
  A key the provider rejects (NCBI 400 "API key invalid" or "not wellformed", OpenAlex 401/403, Software Heritage 401/403; FRED 400 about api_key: no key-less FRED, skipped) is dropped for the rest of the run
  (<state>/keys-invalid.json, names only), the call is retried once without it, and every answer carries key_invalid: [NAME].
Import:
  from gateway import Gateway
  g = Gateway(plugins=['plugins/cs-ai.md'], T='2026-10-26', run='q1')
  g.search('openalex', 'query', n=20) ; g.read('doi:...') ; g.citing('pmid:...') ; g.references('arxiv:...') ; g.related('doi:...')

`sources` block read in each plugin (in its Sources section, fenced ```sources):
  engines: openalex, crossref, arxiv      # required ; engines that are not wired are tolerated but refused when called
  since: 2015                             # optional lower bound (year)
  cap: 60                                 # optional safety cap on calls
  keys: OPENALEX_KEY                      # optional, resolved by key() (env NAME, ~/.config/vp/<name>.key ; KEYS.md), never required
Without plugin: every wired engine. Default T: today (nothing later than yesterday is served).
--case ID (tests only): T, forbidden DOIs and titles from tests/fixtures/bench_cases.json, loaded only when that file exists.
"""
import argparse, datetime as dt, fcntl, hashlib, html, json, os, pathlib, re, sys, time, types, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P)); import code_sources as sc   # python3 -I does not add the script directory
import sources as _reg                                  # tools/sources/: one file per source (CONTRIBUTING.md); the registry derives every table below
from sources._common import *                           # noqa: F401,F403  shared helpers (fetch, jget, Barrier, date_upper, key, live_key...) as gateway.<name>
from sources._common import _before, _mailto, _ua       # noqa: F401  (underscore names are not exported by *)

globals().update({k: v for k, v in _reg.public().items() if k not in globals()})   # compatibility: gateway.search_pubmed, gateway.read_legi, gateway.lf_day...

# ---------------------------------------------------------------- tables derived from the source declarations (sources/__init__.py)
ENGINES = _reg.ENGINES                 # engine -> search(q, n, B, **opts)
CODE_ENGINES = _reg.CODE_ENGINES       # code command -> engine ; never served without plugin
SERVED_BY = _reg.SERVED_BY             # declared source name -> the wired code engine that serves it (tools/check_keys.py)
FILTER_OPT = _reg.FILTER_OPT           # options passed by Gateway.call to each engine


class _Module(types.ModuleType):
    """`gateway.<name> = value` also rebinds <name> in the helper and source modules that hold the same object: tests and tools replace
    gateway.fetch, gateway.STATE, gateway.piste_http, gateway._PISTE_OPENER, and every source sees the replacement."""
    def __setattr__(self, name, value):
        old = self.__dict__.get(name, _reg.MISSING)
        super().__setattr__(name, value)
        if old is not _reg.MISSING and old is not value: _reg.rebind(name, old, value)


sys.modules[__name__].__class__ = _Module


# ---------------------------------------------------------------- routing of identifiers (prefix -> its source; else a source's match(); else DOI)

def read(ident, B):
    s = _reg.owner(ident)
    return s['read'](ident.strip(), B)


def _chain(op, ident, n, B):
    """citing / references / related: the owner's handler, its "not served" message, or (nothing declared) the default source's handler."""
    h = _reg.owner(ident).get(op)
    if h is None: h = _reg.DEFAULT[op]
    return ([], h) if isinstance(h, str) else h(ident, n, B)


def citing(ident, n, B): return _chain('citing', ident, n, B)
def references(ident, n, B): return _chain('references', ident, n, B)
def related(ident, n, B): return _chain('related', ident, n, B)


# ---------------------------------------------------------------- plugins and interface

SKILL_DIR = P.parent


class PluginNotFound(ValueError):
    """A --plugin argument that names no file (message: what was tried and the plugins shipped)."""


def plugin_path(path):
    """--plugin argument -> existing file: the path as given (current directory or absolute), else the same path from the skill directory
    (`plugins/cs-ai.md` works from any directory), else a bare name (`cs-ai`, `cs-ai.md`) in <skill>/plugins/. Never a guess beyond these."""
    p = pathlib.Path(str(path))
    for c in (p, SKILL_DIR / p, SKILL_DIR / 'plugins' / p.name, SKILL_DIR / 'plugins' / (p.name + '.md')):
        if c.is_file(): return c
    shipped = sorted(x.stem for x in (SKILL_DIR / 'plugins').glob('*.md') if not x.name.startswith('_'))
    raise PluginNotFound(f"plugin not found: {str(path)!r} (tried from the current directory {os.getcwd()} and from the skill directory "
                         f"{SKILL_DIR}); give plugins/<name>.md or <name>, shipped: {', '.join(shipped)}")


def read_plugin(path):
    """Reads the ```sources block of a plugin (key: value lines). Without block: no engine declared (reported)."""
    path = plugin_path(path)
    txt = path.read_text(encoding='utf-8')
    m = re.search(r'```sources[^\n]*\n(.*?)```', txt, re.S)
    decl = {}
    if m:
        for line in m.group(1).splitlines():
            line = line.split('#', 1)[0].strip()
            if ':' in line:
                k, v = line.split(':', 1); decl[k.strip().lower()] = v.strip()
    engines = [x.lower() for x in re.split(r'[,\s]+', decl.get('engines', '')) if x]
    code = [x for x in engines if x in CODE_ENGINES.values()]                 # declared code engines, listed apart (code_engines)
    keys = [x for x in re.split(r'[,\s]+', decl.get('keys', '')) if x]
    return {'file': str(path), 'name': pathlib.Path(path).stem, 'declared': bool(m), 'engines': [x for x in engines if x not in code], 'code_engines': code,
            'since': decl.get('since') or None, 'cap': int(decl['cap']) if decl.get('cap', '').isdigit() else None, 'keys': keys}


class Gateway:
    def __init__(self, plugins=(), T=None, case=None, run='vp', state=None, cap=None, since=None, pool=None):
        """pool: None = the searches (counter-<run>.txt); a name = a separate budget with its own counter (counter-<run>.<pool>.txt) and
        its own cap (`cap`, else config `<pool>.call_cap`), journaled with `pool` (tools/verifier.py: pool 'verifier')."""
        self.plugins = [read_plugin(p) for p in plugins]
        if case: self.B = Barrier.from_case(case)
        else:
            low = since or min((int(p['since']) for p in self.plugins if p['since'] and str(p['since']).isdigit()), default=None)
            self.B = Barrier(T or dt.date.today(), since=low)
        declared = [m for p in self.plugins for m in p['engines']]
        self.engines = sorted(set(declared) & set(ENGINES)) if self.plugins else sorted(ENGINES)
        self.code_engines = sorted({m for p in self.plugins for m in p['code_engines']})   # absent without plugin (intended difference)
        self.served_by = {m: SERVED_BY[m] for m in sorted(set(declared) - set(ENGINES)) if SERVED_BY.get(m) in self.code_engines}
        self.not_wired = sorted(set(declared) - set(ENGINES) - set(self.served_by))   # a name served by a declared code engine is not "not wired"
        self.pool = re.sub(r'[^A-Za-z0-9_-]', '_', str(pool)) if pool else None
        if self.pool: self.cap = cap or int((CFG.get(self.pool) or {}).get('call_cap') or 0) or None
        else: self.cap = cap or min((p['cap'] for p in self.plugins if p['cap']), default=None) or CFG['call_cap']['default']
        if not self.cap: raise ValueError(f"no call cap for the pool {self.pool!r}: set {self.pool}.call_cap in tools/config.json or pass cap")
        self.run = re.sub(r'[^A-Za-z0-9_.-]', '_', str(run))
        setattr(sys.modules[__name__], 'STATE', pathlib.Path(state or os.environ.get('VP_STATE') or 'vp-state'))   # rebinds every source
        self.state = STATE
        self.client = sc.CodeClient(cache_dir=self.state)                     # receipts in <state>/requests.jsonl, never the URL nor the token

    def sources(self):
        return {'T': self.B.T.isoformat(), 'bound': f'documents before {self.B.T}', 'since': self.B.since, 'cap': self.cap, **({'pool': self.pool} if self.pool else {}),
                'engines': self.engines, 'not_wired': self.not_wired, 'served_by': self.served_by, 'code_engines': self.code_engines,
                'keys_present': sorted({k for p in self.plugins for k in p['keys'] if live_key(k)} | self._github_state()),
                'key_invalid': sorted(sc.invalid_keys(self.state)),
                'commands': ['search-' + m for m in self.engines] + ['read', 'citing', 'references', 'related'] + [c for c, m in CODE_ENGINES.items() if m in self.code_engines],
                'plugins': [{'name': p['name'], 'file': p['file'], 'sources_block': p['declared']} for p in self.plugins],
                **({'user_sources': _reg.USER_SOURCES} if _reg.USER_SOURCES else {})}

    def _github_state(self):
        if 'code' not in self.code_engines: return set()
        try: return {'GITHUB'} if sc.read_token() else set()
        except ValueError: return {'GITHUB: invalid (credential_invalid, KEYS.md)'}

    def _count(self):
        self.state.mkdir(parents=True, exist_ok=True)
        with open(self.state / (f'counter-{self.run}.txt' if not self.pool else f'counter-{self.run}.{self.pool}.txt'), 'a+') as f:
            fcntl.flock(f, fcntl.LOCK_EX); f.seek(0); k = int(f.read() or 0)
            if k >= self.cap: return None
            f.seek(0); f.truncate(); f.write(str(k + 1))
        return k + 1

    def call(self, cmd, arg, n=20, **opt):
        """One counted and journaled command. opt: language, repo (search-code); court, date_from, date_to (search-justice-administrative)."""
        if cmd == 'sources': return self.sources()
        n = max(1, min(int(n), 100 if cmd in ('citing', 'references', 'related') else 50))
        if cmd in CODE_ENGINES and CODE_ENGINES[cmd] not in self.code_engines:
            return {'refusal': f"engine '{CODE_ENGINES[cmd]}' not declared by the plugins (sources block); available code engines: {', '.join(self.code_engines) or 'none'}"}
        spec = _reg.CODE_COMMANDS.get(cmd)
        if spec and spec.get('form') and not re.fullmatch(spec['form'], arg): return {'refusal': spec['form_msg']}
        via = (_reg.id_spec(arg) or {}).get('code_engine') if cmd == 'read' else None   # an identifier read through a code engine (osv:)
        if via and via not in self.code_engines:
            return {'refusal': f"engine '{via}' not declared by the plugins (sources block); available code engines: " + (', '.join(self.code_engines) or 'none')}
        if cmd.startswith('search-') and cmd[7:] not in self.engines and cmd not in CODE_ENGINES:
            return {'refusal': f"engine '{cmd[7:]}' not declared by the plugins (sources block) or not wired; available engines: {', '.join(self.engines)}"}
        if not (cmd.startswith('search-') or cmd in ('read', 'citing', 'references', 'related') or cmd in CODE_ENGINES):
            return {'refusal': f"unknown command '{cmd}'"}
        k = self._count()
        if k is None:
            if self.pool: return {'refusal': f"CAP reached ({self.cap} calls of the {self.pool} budget, {self.pool}.call_cap of tools/config.json)", 'pool': self.pool}
            return {'refusal': f"CAP reached ({self.cap} calls): stop searching and return your list."}
        B = self.B; B.excluded = 0; err = None; extra = {}
        ja_opt = {k: opt[k] for k in FILTER_OPT.get(cmd, ()) if opt.get(k)}   # engine filters (FILTER_OPT, PISTE block)
        if ja_opt: extra['filters'] = ja_opt
        engine = CODE_ENGINES.get(cmd) or (cmd[7:] if cmd.startswith('search-') else None)
        try:
            if cmd in CODE_ENGINES: res, total = self._code(cmd, arg, n, opt, B, extra), None
            elif via: res, total = _reg.owner(arg)['read'](arg.strip(), B, client=self.client), None
            elif cmd == 'read': res, total = read(arg, B), None
            else:
                fn = ENGINES[cmd[7:]] if cmd.startswith('search-') else {'citing': citing, 'references': references, 'related': related}[cmd]
                res, total = fn(arg, n, B, **ja_opt) if ja_opt else fn(arg, n, B)
        except Exception as e:
            res, total, err = {'error': f'{type(e).__name__}: {str(e)[:200]}'}, None, str(e)
        inv = sorted(sc.invalid_keys(self.state))                            # names of the keys rejected by their provider in this run
        out = {'call': k, 'cap': self.cap, **({'pool': self.pool} if self.pool else {}), 'bound': f'documents before {B.T}', 'index_total': total,
               'excluded_post_T_or_forbidden': B.excluded, 'results': res, 'engine': engine, 'query': arg, 'n': n, **extra, **({'key_invalid': inv} if inv else {})}
        with open(self.state / 'journal.jsonl', 'a') as f:
            f.write(json.dumps({'utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'run': self.run, **({'pool': self.pool} if self.pool else {}), 'T': B.T.isoformat(), 'call': cmd, 'engine': engine,
                                'query': arg, **({'filters': ja_opt} if ja_opt else {}), 'n': n, 'count': len(res) if isinstance(res, list) else None, 'excluded': B.excluded, 'error': err, **({'key_invalid': inv} if inv else {}),
                                'ids': [r.get('id') for r in res] if isinstance(res, list) else [res.get('id')] if isinstance(res, dict) else []},
                               ensure_ascii=False) + '\n')
        return out

    def _code(self, cmd, arg, n, opt, B, extra):
        """Code engines (declared `commands` of the sources): same counter, same journal, same envelope; date barrier by _date_filter
        unless the source applies its own (date_filter False)."""
        spec = _reg.CODE_COMMANDS[cmd]
        res = spec['run'](self, arg, n, opt, B, extra)
        if not spec['date_filter']: return res
        res = self._date_filter(res, B, extra)
        return res if res is not None else {'refusal': 'after T'}

    def _date_filter(self, x, B, extra):
        """Date barrier of the code engines: dated >= T removed and counted (Barrier.ok); undated kept with dating "absent"."""
        if isinstance(x, list): return [y for y in (self._date_filter(i, B, extra) for i in x) if y is not None]
        if not isinstance(x, dict): return x
        dates = [x[k] for k in ('date', 'date_visited', 'date_registry', 'date_deps_dev') if x.get(k)]   # every date carried
        if not dates: x['dating'] = 'absent'; extra['warning'] = 'live index: results cannot be dated'
        elif not B.ok(None, *dates): return None
        for k in ('repos', 'models', 'datasets', 'spaces'):
            if k in x: x[k] = self._date_filter(x[k], B, extra)
        return x

    def search(self, engine, q, n=20, **opt): return self.call('search-' + engine, q, n, **opt)
    def read(self, ident): return self.call('read', ident)
    def citing(self, ident, n=25): return self.call('citing', ident, n)
    def references(self, ident, n=50): return self.call('references', ident, n)
    def related(self, ident, n=25): return self.call('related', ident, n)




def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plugin', action='append', default=[], help='plugin file (repeatable)')
    ap.add_argument('--T', help='date of the question YYYY-MM-DD (default: today)')
    ap.add_argument('--case', help='date-barrier case id from tests/fixtures/bench_cases.json (tests only: fixes T, forbidden DOIs and titles)')
    ap.add_argument('--run', default='vp'); ap.add_argument('--state', default=None); ap.add_argument('--cap', type=int, default=None)
    ap.add_argument('--since', default=None)
    ap.add_argument('cmd'); ap.add_argument('arg', nargs='*'); ap.add_argument('--n', type=int, default=20)
    ap.add_argument('--language', default=None); ap.add_argument('--repo', default=None, help='search-code: language / owner/repo filters')
    ap.add_argument('--court', default=None, help='search-justice-administrative: exact court code (CE, TA75, CAA69)')
    ap.add_argument('--from', dest='date_from', default=None); ap.add_argument('--to', dest='date_to', default=None, help='search-justice-administrative: decision-date window YYYY-MM-DD')
    ap.add_argument('--chamber', default=None, help='search-judilibre: chamber key (civ1, soc, cr...); --court cc|ca|tj|tcom'); ap.add_argument('--fund', default=None, help='search-legifrance: code|loda|jorf')
    a = ap.parse_args()
    try: g = Gateway(a.plugin, T=a.T, case=a.case, run=a.run, state=a.state, cap=a.cap, since=a.since)
    except PluginNotFound as e: print(f'gateway.py: {e}', file=sys.stderr); sys.exit(2)
    print(json.dumps(g.call(a.cmd, ' '.join(a.arg), a.n, language=a.language, repo=a.repo, court=a.court, date_from=a.date_from, date_to=a.date_to, chamber=a.chamber, fund=a.fund), ensure_ascii=False))


if __name__ == '__main__':
    main()
