#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Which keys are missing? Offline, standard library. Reads the plugins (```sources block, `keys:` line) and applies the REAL
key resolution: `code_sources.key()` (environment variable NAME, then ~/.config/vp/<name in lower case>.key), including for the
GitHub token (`read_token()`). Prints per plugin: active sources, degraded for lack of a key, skipped for lack of a key, not wired;
with the exact variable name, free or not, and the URL to obtain it (KEYS.md). Never a key value. Ends with the contradictor line
("Contradictors: none (...)" or the configured families, names only, and whether OPENROUTER_API_KEY is present) and the mode line
("Mode: standard" or "Mode: audit (set by VP_MODE|~/.config/vp/mode)").
Usage: check_keys.py [--plugin P.md ...] [--json] [--announce]   (without --plugin: every plugins/*.md except _TEMPLATE). Exit code: 0.
--announce: prints the full report (links included) on the first run and each time the set of active sources or of present keys
changes for an examined plugin (key added, removed, expired); otherwise an empty string. The fingerprint (names only, never
a value) is kept in ~/.config/vp/keys-state.json, created when needed. The "Source coverage" block of the report is due at every run.
--suggest "<angles>": lexically matches the angles of the question (SKILL.md section 2) with the `useful_when:` lines of the plugins (sources
with a FREE key only, never paid nor under a restrictive licence) for the sources missing for lack of a key; at most 2 suggestions, else empty.
Import: report(plugins) -> dict; text(rep) -> str; announce(rep) -> str; suggest(rep, angles) -> [dict]; mode() -> 'standard'|'audit';
contradictors() -> [family names]."""
import argparse, json, os, pathlib, re, sys, unicodedata
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P)); import gateway as gw, code_sources as sc   # noqa: E702  (python3 -I does not add the script directory)
import sources as _reg   # noqa: E402  (source registry: the key catalogue below is derived from it)


def _catalogue():
    """variable -> source, gateway engine concerned (None = not wired), effect without the key (degraded | skipped), whether the gateway really
    sends it today (`passed`; otherwise only detected), reason, free or not, URL, and the other variable of a pair. Derived from the `key` spec
    of each source declaration (tools/sources/, CONTRIBUTING.md); KEYS.md documents the same keys for humans."""
    out = {}
    for _, k in _reg.key_specs():
        for v in k['vars']:
            other = [x for x in k['vars'] if x != v]
            out[v] = dict(source=k['source'], engine=k['engine'], without=k['without'], passed=k['passed'], reason=k['reason'], free=k['free'], url=k['url'],
                          **({'pair': other[0]} if other else {}))
    return out


CATALOGUE = _catalogue()
WIRED = set(gw.ENGINES) | set(gw.CODE_ENGINES.values())
# Suggestion (--suggest): displayed name, registration delay, and whether the source may be proposed (free registration, non-restrictive licence).
SUGGESTION = {v: tuple(k['suggest']) for _, k in _reg.key_specs() if k.get('suggest') for v in k['vars']}
PRESENT = {v: k['present'] for _, k in _reg.key_specs() if k.get('present') for v in k['vars']}   # own resolution (GitHub token: read_token)
STOPWORDS = {'the', 'and', 'for', 'with', 'from', 'into', 'over', 'that', 'this', 'are', 'not', 'when', 'between', 'without', 'non', 'about', 'any', 'all'}
NOTE_NOT_WIRED = 'engine not wired: the key has no effect until the engine is wired'
NOTE_NOT_PASSED = 'declared, no effect until wired (the gateway does not pass it yet)'


def mode():
    """'audit' when env VP_MODE == 'audit' or ~/.config/vp/mode contains 'audit'; otherwise 'standard'."""
    if os.environ.get('VP_MODE', '').strip().lower() == 'audit': return 'audit'
    try:
        if (pathlib.Path.home() / '.config' / 'vp' / 'mode').read_text(encoding='utf-8').strip().lower() == 'audit': return 'audit'
    except OSError: pass
    return 'standard'


def mode_line():
    return 'Mode: standard' if mode() == 'standard' else 'Mode: audit (set by VP_MODE|~/.config/vp/mode)'


def contradictors():
    """Configured contradictor families (names only, same resolution as tools/contradictor.py): VP_CONTRADICTORS, else
    ~/.config/vp/contradictors, else tools/config.json contradictor.families (empty by default = option absent)."""
    raw = os.environ.get('VP_CONTRADICTORS', '')
    if not raw.strip():
        try: raw = (pathlib.Path.home() / '.config' / 'vp' / 'contradictors').read_text(encoding='utf-8')
        except OSError: raw = ''
    if not raw.strip():
        try: raw = ','.join(str(x) for x in (json.loads((P / 'config.json').read_text(encoding='utf-8')).get('contradictor') or {}).get('families') or [])
        except (OSError, ValueError): raw = ''
    out = []
    for line in raw.splitlines():
        for n in re.split(r'[,\s]+', line.split('#', 1)[0].strip()):
            n = n.strip().lower()
            if n and n not in out: out.append(n)
    return out


def providers():
    """OpenAI-compatible providers of the contradictor (names, url, key variable), config then VP_CONTRADICTOR_PROVIDERS (JSON)."""
    try: out = {k.lower(): v for k, v in ((json.loads((P / 'config.json').read_text(encoding='utf-8')).get('contradictor') or {}).get('providers') or {}).items() if isinstance(v, dict)}
    except (OSError, ValueError): out = {}
    raw = os.environ.get('VP_CONTRADICTOR_PROVIDERS', '').strip()
    if raw:
        try: out.update({k.lower(): v for k, v in json.loads(raw).items() if isinstance(v, dict)})
        except (ValueError, AttributeError): pass
    return out


def contradictors_line():
    """Names only, and for each API provider whether its key variable is present; never a value."""
    fams = contradictors()
    if not fams:
        return ('Contradictors: none (optional, code plugin: VP_CONTRADICTORS or ~/.config/vp/contradictors = openai[:<model>] (Codex CLI), claude[:<model>] (claude -p), '
                '<provider>:<model> for an OpenAI-compatible API, providers: ' + ', '.join(sorted(providers())) + '; KEYS.md)')
    provs = providers(); parts = []
    for f in fams:
        via = f.split(':', 1)[0]
        if via in ('openai', 'claude'): parts.append(f); continue
        prov = provs.get(via)
        if not prov: parts.append(f + ' (unknown provider: skipped)'); continue
        if ':' not in f or not f.split(':', 1)[1].strip(): parts.append(f + ' (model id required: <provider>:<model>; skipped)'); continue
        kv = prov.get('key')
        parts.append(f + (f" ({kv} {'present' if gw.key(kv) else 'absent: skipped, credential_missing'})" if kv else ''))
    return 'Contradictors: ' + ', '.join(parts) + ' (set by VP_CONTRADICTORS|~/.config/vp/contradictors|tools/config.json)'


def words(text):
    """Normalised keywords: lower case, no accent, >= 3 letters, simple plural removed, stop words excluded."""
    t = unicodedata.normalize('NFKD', text.lower()).encode('ascii', 'ignore').decode()
    return {re.sub(r'(s|x)$', '', m) for m in re.findall(r'[a-z0-9][a-z0-9/-]{2,}', t)} - STOPWORDS


def useful_when(path):
    """Line `useful_when: source=text ; source=text` of the ```sources block; {} if absent."""
    m = re.search(r'```sources[^\n]*\n(.*?)```', pathlib.Path(path).read_text(encoding='utf-8'), re.S)
    for line in (m.group(1).splitlines() if m else []):
        line = line.split('#', 1)[0].strip()
        if line.lower().startswith('useful_when:'):
            return {s.strip().lower(): t.strip() for s, _, t in (e.partition('=') for e in line.split(':', 1)[1].split(';')) if s.strip() and t.strip()}
    return {}


def suggest(rep, angles, maxi=2):
    """Sources missing for lack of a key whose `useful_when` shares >= 2 keywords with the angles; free ones only, and only keys the
    gateway really sends today (a declared key with no effect is never suggested); <= maxi, best first."""
    q = words(angles); seen = {}; out = []
    for r in rep['plugins']:
        uw = useful_when(r['file'])
        for i in r['skipped'] + r['degraded']:
            if not i.get('passed_by_gateway'): continue
            var = i['variable'].split(' + ')[0]
            name, delay, ok = SUGGESTION.get(var, (None, None, False))
            text_uw = uw.get(CATALOGUE[var]['source'].split(' ')[0]) if var in CATALOGUE else None
            if not (ok and text_uw) or name in seen: continue
            common = sorted(q & words(text_uw))
            if len(common) >= 2:
                seen[name] = True
                out.append({'source': name, 'plugin': r['plugin'], 'variable': i['variable'], 'url': i['url'], 'delay': delay, 'words': common,
                            'text': f"This question would probably have benefited from {name} (free registration, {delay}: {i['url']}; variable {i['variable']}; words: {', '.join(common)})."})
    return sorted(out, key=lambda s: -len(s['words']))[:maxi]


def present(name):
    """Real resolution: the key spec's own `present` (GitHub token: read_token(), None absent, 'invalid' if refused), key() for the rest.
    Never the value."""
    if name in PRESENT:
        try: return bool(PRESENT[name]())
        except ValueError: return 'invalid'
    return bool(gw.key(name))


def served(name, declared):
    """The wired code engine that serves a declared source name (gateway.SERVED_BY: github -> code, hf-papers -> paper-code...) when that
    engine is declared too; otherwise None (the name stays "not wired")."""
    e = getattr(gw, 'SERVED_BY', {}).get(name)
    return e if e in WIRED and e in declared else None


def plugin_report(path):
    d = gw.read_plugin(path)
    declared = list(d['engines']) + list(d['code_engines'])
    state = {k: present(k) for k in d['keys']}
    r = {'plugin': d['name'], 'file': d['file'], 'sources_block': d['declared'], 'keys_declared': list(d['keys']),
         'keys_present': sorted(k for k, v in state.items() if v is True), 'keys_absent': sorted(k for k, v in state.items() if v is not True),
         'active': [m for m in declared if m in WIRED], 'degraded': [], 'skipped': [], 'not_wired': [m for m in declared if m not in WIRED and served(m, declared) is None],
         'served_by': {m: served(m, declared) for m in declared if m not in WIRED and served(m, declared)}}
    for k in d['keys']:
        c = CATALOGUE.get(k)
        if c is None:
            r.setdefault('unknown_keys', []).append(k); continue
        ok = state[k] is True and (c.get('pair') is None or state.get(c['pair']) is True)
        if ok: continue
        item = {'source': c['source'], 'variable': k if not c.get('pair') else f"{k} + {c['pair']}", 'state': 'invalid' if state[k] == 'invalid' else 'absent',
                'reason': c['reason'], 'free': c['free'], 'url': c['url'], 'passed_by_gateway': c['passed']}
        if c.get('pair') and k > c['pair']: continue                     # the PISTE pair is reported once
        if c['engine'] is None or c['engine'] not in WIRED:
            item['note'] = NOTE_NOT_WIRED
            r['keyed_not_wired'] = r.get('keyed_not_wired', []) + [item]
        elif c['without'] == 'skipped': r['skipped'].append(item)
        else:
            if not c['passed']: item['note'] = NOTE_NOT_PASSED
            r['degraded'].append(item)
    return r


def report(plugins=()):
    files = [pathlib.Path(p) for p in plugins] or sorted(p for p in (P.parent / 'plugins').glob('*.md') if not p.name.startswith('_'))
    rs = [plugin_report(p) for p in files]
    missing = sorted({i['variable'] for r in rs for i in r['skipped'] + r['degraded'] + r.get('keyed_not_wired', [])})
    return {'plugins': rs, 'missing_keys': missing, 'ok': not any(r['skipped'] or r['degraded'] for r in rs), 'mode': mode(), 'contradictors': contradictors()}


def text(rep):
    def line(i):
        return (f"{i['source']} - {i['variable']} {i['state']} ({i['reason']}); {i['free']}; {i['url']}" + (f"; {i['note']}" if i.get('note') else ''))
    out = []
    for r in rep['plugins']:
        out.append(f"{r['file']}" + ('' if r['sources_block'] else '   (no ```sources block)'))
        out.append('  active         : ' + (', '.join(r['active']) or 'none'))
        out.append('  degraded       : ' + ('\n                   '.join(line(i) for i in r['degraded']) or 'none (for lack of a key)'))
        out.append('  skipped        : ' + ('\n                   '.join(line(i) for i in r['skipped']) or 'none (for lack of a key)'))
        if r.get('keyed_not_wired'):
            out.append('  keyed, not wired : ' + '\n                   '.join(line(i) for i in r['keyed_not_wired']))
        if r.get('served_by'): out.append('  served by      : ' + ', '.join(f'{m} (via {e})' for m, e in r['served_by'].items()))
        out.append('  not wired      : ' + (', '.join(r['not_wired']) or 'none'))
        out.append('  keys present   : ' + (', '.join(r['keys_present']) or 'none') + '; absent: ' + (', '.join(r['keys_absent']) or 'none'))
        if r.get('unknown_keys'): out.append('  keys outside the catalogue (KEYS.md to complete): ' + ', '.join(r['unknown_keys']))
    out.append('Missing keys: ' + (', '.join(rep['missing_keys']) or 'none') + '. How to obtain and install them: python3 -I tools/setup_keys.py <NAME> (lists, installs and checks live; KEYS.md).')
    out.append(contradictors_line())
    out.append(mode_line())
    return '\n'.join(out)


def state_path():
    return pathlib.Path.home() / '.config' / 'vp' / 'keys-state.json'


def fingerprint(r):
    """What, if it changes, deserves a new announcement: active sources, present keys (names), sources skipped/degraded/keyed not wired."""
    return {'active': sorted(r['active']), 'keys_present': r['keys_present'],
            'missing': sorted(i['variable'] + ':' + i['state'] for i in r['skipped'] + r['degraded'] + r.get('keyed_not_wired', []))}


def announce(rep, state=None):
    """Text to display in the first message, or '' if nothing changed since the last run for these plugins. Updates the state."""
    state = pathlib.Path(state) if state else state_path()
    try: memo = json.loads(state.read_text(encoding='utf-8'))
    except (OSError, ValueError): memo = {}
    known = memo.get('plugins') if isinstance(memo.get('plugins'), dict) else {}
    current = {r['plugin']: fingerprint(r) for r in rep['plugins']}
    changed = any(known.get(name) != e for name, e in current.items())
    if changed:
        try:
            state.parent.mkdir(parents=True, exist_ok=True)
            state.write_text(json.dumps({'version': 1, 'note': 'fingerprint of the active sources and of the names of present keys per plugin; never a value',
                                         'plugins': {**known, **current}}, ensure_ascii=False, indent=1), encoding='utf-8')
        except OSError: pass                                                # state not writable: announce anyway
    return ('Keys: ' + ('first run' if not known else 'the set of active sources or keys has changed') + ' - sources skipped or degraded for lack of a key, and how to obtain each key (KEYS.md):\n'
            + text(rep)) if changed else ''


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plugin', action='append', default=[], help='plugin file (repeatable); default: every plugins/*.md')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--announce', action='store_true', help='text for the first message (first run or change), otherwise an empty string')
    ap.add_argument('--suggest', metavar='ANGLES', help='angles of the question: suggestions of missing free-key sources (<= 2), otherwise empty')
    a = ap.parse_args(argv)
    rep = report(a.plugin)
    if a.suggest is not None:
        s = suggest(rep, a.suggest)
        print(json.dumps({'suggestions': s}, ensure_ascii=False) if a.json else '\n'.join(x['text'] for x in s), end='\n' if s or a.json else '')
    elif a.announce:
        t = announce(rep)
        print(json.dumps({'announce': t, 'changed': bool(t), 'mode': rep['mode'], 'contradictors': rep['contradictors']}, ensure_ascii=False) if a.json else t, end='' if not t and not a.json else '\n')
    else: print(json.dumps(rep, ensure_ascii=False, indent=1) if a.json else text(rep))
    return 0


if __name__ == '__main__':
    sys.exit(main())
