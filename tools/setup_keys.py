#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Install, check or remove an optional API key in one command (standard library). The value is typed without echo (getpass), or read
from stdin one per line when stdin is not a terminal (scripts); it is stripped and written to ~/.config/vp/<name in lower case>.key
(directory 0700, file 0600, atomic write), the file that `code_sources.key()` reads (KEYS.md). No value is ever printed or logged.
After installing, a LIVE check sends one minimal request per source through the gateway's own code paths (gateway.fetch for OpenAlex
and PubMed, the FRED engine for FRED, CodeSearch/Provenance for GitHub and Software Heritage, the PISTE token and engines for Judilibre and Legifrance; a free
GET on the provider for a contradictor key) and prints one plain verdict line per source.
The identification contact VP_CONTACT (an e-mail address, KEYS.md) is installed the same way (`setup_keys.py contact`); its form is checked
(name@domain) and its live check is one Unpaywall request.
Usage: setup_keys.py                list the known keys (present or absent, what each unlocks), then ask which one to install
       setup_keys.py NAME           install NAME (variable name in any case, or short name: contact, piste, openalex, ncbi, github, swh, openrouter...)
       setup_keys.py NAME --check   live check of the installed key only
       setup_keys.py NAME --remove  delete the key file(s) after confirmation (y)
Exit code: 0 ok, 1 check failed (or key not installed), 2 usage (unknown name, empty or malformed value)."""
import argparse, datetime as dt, getpass, json, os, pathlib, re, sys, tempfile, urllib.error, urllib.parse, urllib.request
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P)); import check_keys as ck, code_sources as sc, gateway as gw   # noqa: E702  (python3 -I does not add the script directory)

KEYS = {v: k for _, k in ck._reg.key_specs() for v in k['vars']}            # variable -> key spec of its source (tools/sources/)
LABEL = {k['vars'][0]: list(k['labels']) for k in KEYS.values() if k.get('labels')}   # sources checked live per key (others: not wired, no live check)
PROMPT = {v: t for k in KEYS.values() for v, t in (k.get('prompt') or {}).items()}
HINT = {k['vars'][0]: k['hint'] for k in KEYS.values() if k.get('hint')}
REFUSED = {k['vars'][0]: k['refused'] for k in KEYS.values() if k.get('refused')}
REFUSED_DEFAULT = 'key refused — check you copied it whole'
FORM = {k['vars'][0]: tuple(k['form']) for k in KEYS.values() if k.get('form')}   # (pattern, message): the value's expected form (VP_CONTACT: an e-mail)


def short(var):
    """Short name derived from the variable: VP_ prefix and _API_KEY / _KEY / _TOKEN / _CLIENT_ID / _CLIENT_SECRET suffix removed."""
    return re.sub(r'_(API_KEY|KEY|TOKEN|CLIENT_ID|CLIENT_SECRET)$', '', re.sub(r'^VP_', '', var)).lower()


def entries():
    """Known keys, one entry per installable unit (the PISTE pair is one entry): catalogue of check_keys, then contradictor providers."""
    out, seen = [], set()
    for var, c in ck.CATALOGUE.items():
        if var in seen: continue
        vs = [var] + ([c['pair']] if c.get('pair') else []); seen |= set(vs)
        wired = c['passed'] and c['engine'] in ck.WIRED
        out.append(dict(name=short(var), vars=vs, url=c['url'], free=c['free'], aliases={short(var), c['source'].split(' ')[0]} | {v.lower() for v in vs},
                        unlocks=f"{ck.SUGGESTION.get(var, (c['source'],))[0]}; without it: {c['reason']}" + ('' if wired else ' (' + ck.NOTE_NOT_WIRED + ')'), wired=wired))
    for prov, d in sorted(ck.providers().items()):
        var = d.get('key')
        if not var or var in seen: continue
        seen.add(var)
        out.append(dict(name=short(var), vars=[var], url=d.get('keys_url') or "the provider's website (KEYS.md)", free='paid per call by the provider',
                        aliases={short(var), prov, var.lower()}, unlocks=f'contradictor family {prov}:<model> (option, tools/contradictor.py)', wired=True,
                        provider=prov, spec=d))
    return out


def find(name):
    n = name.strip().lower()
    return next((e for e in entries() if n in e['aliases']), None)


def state(e):
    s = [ck.present(v) for v in e['vars']]
    return 'invalid' if 'invalid' in s else 'present' if all(x is True for x in s) else 'absent'


def listing():
    lines = []
    for i, e in enumerate(entries(), 1):
        lines.append(f"{i:2}. {e['name']:<10} {' + '.join(e['vars'])} [{state(e)}] - {e['unlocks']}; {e['free']}")
    return '\n'.join(lines)


def keyfile(var): return pathlib.Path.home() / '.config' / 'vp' / (var.lower() + '.key')


def ask(prompt):
    """One secret: getpass on a terminal (never echoed), else one line of stdin (never echoed either). Stripped; '' at end of input."""
    if sys.stdin.isatty(): return getpass.getpass(prompt + ' (typing is hidden): ').strip()
    return sys.stdin.readline().strip()


def answer(prompt):
    """A visible answer (menu choice, confirmation): input() on a terminal, else one line of stdin."""
    if sys.stdin.isatty():
        try: return input(prompt).strip()
        except EOFError: return ''
    print(prompt, flush=True); return sys.stdin.readline().strip()


def write_key(var, value):
    """Atomic write of ~/.config/vp/<var lower>.key: directory 0700, temporary file 0600 in the same directory, then rename."""
    f = keyfile(var); f.parent.mkdir(parents=True, exist_ok=True); os.chmod(f.parent, 0o700)
    fd, tmp = tempfile.mkstemp(dir=f.parent, prefix='.' + f.name + '.')
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as w: w.write(value + '\n'); w.flush(); os.fsync(w.fileno())
        os.replace(tmp, f)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def why(e):
    """Short cause of a failed check, never a value (codes and exception type names only)."""
    code = getattr(e, 'code', None)
    if code == 429 or 'rate_limited' in str(e): return 'service busy (HTTP 429), try again in a few minutes'
    if code: return f'service answered HTTP {code}, try again later'
    s = str(e)
    return (s if re.fullmatch(r'[\w:. -]{1,80}', s) and ('provider_error' in s or 'transport_error' in s or 'redirect' in s) else type(e).__name__) + ', try again later'


def check(e):
    """[(label, ok, text)] for entry e, one minimal live request per source, in a temporary state dir (no cache, no stale token).
    The request is the source's own `check` (key spec in tools/sources/): 'ok' | 'refused' | ('fail', text) | an exception, or one
    such outcome per label ({label: outcome})."""
    var = e['vars'][0]
    if state(e) == 'absent':
        return [(l, False, f"not installed (run: python3 -I tools/setup_keys.py {e['name']})") for l in LABEL.get(var, [e.get('provider') or e['name']])]
    if not e['wired']: return [(e['name'], True, 'installed; no live check: VP does not use this key yet (engine not wired)')]
    with tempfile.TemporaryDirectory(prefix='vp-setup-') as tmp:
        gw.STATE = pathlib.Path(tmp)
        if e.get('provider'): return [(e['provider'], *check_provider(e))]
        spec = KEYS.get(var) or {}
        labels = LABEL.get(var, [e['name']]); run = spec.get('check')
        if run is None: return [(labels[0], True, 'installed; no live check for this key')]
        try: r = run(tmp)
        except Exception as x: return [(labels[0], False, 'could not be checked: ' + why(x))]
        rows = r if isinstance(r, dict) else {labels[0]: r}
        return [(label, *verdict(o, REFUSED.get(var, REFUSED_DEFAULT))) for label, o in rows.items()]


def verdict(o, refused):
    """(ok, text) of one live-check outcome."""
    if isinstance(o, BaseException): return False, 'could not be checked: ' + why(o)
    if o == 'ok': return True, 'OK'
    if o == 'refused': return False, refused
    return False, o[1] if isinstance(o, tuple) else f'not checked ({o})'


def check_provider(e):
    """One free GET with the key as Bearer (provider check_url, else <url without /chat/completions>/models); https only, no redirect."""
    d, k = e['spec'], sc.key(e['vars'][0])
    url = d.get('check_url') or re.sub(r'/chat/completions/?$', '', d.get('url') or '') + '/models'
    if not url.startswith('https://'): return False, 'not checked: the provider url is not https (a key is only sent over https)'
    try:
        with urllib.request.build_opener(sc._NoRedirect()).open(urllib.request.Request(url, headers={'Authorization': 'Bearer ' + k, 'User-Agent': sc.UA}), timeout=30) as r: r.read(65536)
        return True, 'OK'
    except urllib.error.HTTPError as x:
        if x.code in (401, 403): return False, 'key refused — check you copied it whole'
        return False, 'could not be checked: ' + why(x)
    except Exception as x: return False, 'could not be checked: ' + why(x)


def report(e):
    rows = check(e)
    for label, ok, txt in rows: print(f'{label}: {txt}')
    return 0 if all(ok for _, ok, _ in rows) else 1


def install(e):
    print(f"Key: {' + '.join(e['vars'])} - {e['unlocks']}.")
    print(('What to enter: ' if e['vars'][0] in FORM else 'Get it here: ') + e['url'] + (f" ({HINT[e['vars'][0]]})" if e['vars'][0] in HINT else ''))
    vals = []
    for v in e['vars']:
        x = ask(PROMPT.get(v, f'Paste {v}'))
        if not x: print(f'Nothing entered for {v}: nothing written.', file=sys.stderr); return 2
        if not re.fullmatch(r'[\x21-\x7e]+', x): print(f'{v}: the value contains spaces or unusual characters; copy it again (nothing written).', file=sys.stderr); return 2
        if v in FORM and not re.fullmatch(FORM[v][0], x): print(f'{v}: {FORM[v][1]} (nothing written).', file=sys.stderr); return 2
        vals.append(x)
    for v, x in zip(e['vars'], vals): write_key(v, x); print(f'Saved {v} in ~/.config/vp/{v.lower()}.key (readable by you only).')
    for v in e['vars']:
        if os.environ.get(v, '').strip(): print(f'Note: the environment variable {v} is set and takes precedence over the file; the check below uses it.')
    print('Checking with the service...')
    return report(e)


def remove(e):
    files = [keyfile(v) for v in e['vars'] if keyfile(v).exists()]
    if not files: print(f"Nothing to remove: no file for {' + '.join(e['vars'])} in ~/.config/vp/."); return 0
    if answer('Delete ' + ', '.join('~/.config/vp/' + f.name for f in files) + '? [y/N] ').lower() not in ('y', 'yes'): print('Nothing deleted.'); return 0
    for f in files: f.unlink(); print(f'Deleted ~/.config/vp/{f.name}.')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('name', nargs='?', help='key to install (variable name or short name); none = list and ask')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--check', action='store_true', help='live check of the installed key only')
    g.add_argument('--remove', action='store_true', help='delete the key file(s) after confirmation')
    a = ap.parse_args(argv)
    if a.name is None:
        if a.check or a.remove: print('--check and --remove need a key name.', file=sys.stderr); return 2
        print('Keys VanishingPoint can use (all optional):\n' + listing())
        c = answer('Which key to install? (number or name, Enter to quit) ')
        if not c: return 0
        es = entries()
        e = es[int(c) - 1] if c.isdigit() and 1 <= int(c) <= len(es) else find(c)
    else: e = find(a.name)
    if e is None:
        print(f"Unknown key name '{a.name or c}'. Known keys:\n" + listing(), file=sys.stderr); return 2
    return report(e) if a.check else remove(e) if a.remove else install(e)


if __name__ == '__main__':
    sys.exit(main())
