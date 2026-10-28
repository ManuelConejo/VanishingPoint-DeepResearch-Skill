#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Install, check or remove an optional API key in one command (standard library). The value is typed without echo (getpass), or read
from stdin one per line when stdin is not a terminal (scripts); it is stripped and written to ~/.config/vp/<name in lower case>.key
(directory 0700, file 0600, atomic write), the file that `code_sources.key()` reads (KEYS.md). No value is ever printed or logged.
After installing, a LIVE check sends one minimal request per source through the gateway's own code paths (gateway.fetch for OpenAlex
and PubMed, the FRED engine for FRED, CodeSearch/Provenance for GitHub and Software Heritage, the PISTE token and engines for Judilibre and Legifrance; a free
GET on the provider for a contradictor key) and prints one plain verdict line per source.
Usage: setup_keys.py                list the known keys (present or absent, what each unlocks), then ask which one to install
       setup_keys.py NAME           install NAME (variable name in any case, or short name: piste, openalex, ncbi, github, swh, openrouter...)
       setup_keys.py NAME --check   live check of the installed key only
       setup_keys.py NAME --remove  delete the key file(s) after confirmation (y)
Exit code: 0 ok, 1 check failed (or key not installed), 2 usage (unknown name, empty or malformed value)."""
import argparse, datetime as dt, getpass, json, os, pathlib, re, sys, tempfile, urllib.error, urllib.parse, urllib.request
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P)); import check_keys as ck, code_sources as sc, gateway as gw   # noqa: E702  (python3 -I does not add the script directory)

LABEL = {'OPENALEX_KEY': ['OpenAlex'], 'NCBI_API_KEY': ['PubMed (NCBI)'], 'VP_GITHUB_TOKEN': ['GitHub code search'], 'SWH_TOKEN': ['Software Heritage'],
         'PISTE_CLIENT_ID': ['Judilibre', 'Légifrance'], 'FRED_API_KEY': ['FRED / ALFRED']}                     # sources checked live per key (others: not wired, no live check)
PROMPT = {'PISTE_CLIENT_ID': 'PISTE Client ID', 'PISTE_CLIENT_SECRET': 'PISTE Client Secret'}
HINT = {'PISTE_CLIENT_ID': 'create an application on piste.gouv.fr, subscribe it to the Judilibre and Légifrance APIs (production, accept their terms), '
                           'then copy its Client ID and Client Secret (piste.gouv.fr > Applications)'}
REFUSED = {'PISTE_CLIENT_ID': 'identifiers refused — check the Client ID and Client Secret (piste.gouv.fr > Applications)'}
SUBSCRIBE = 'identifiers accepted but the application is not subscribed to this API (piste.gouv.fr > Applications > tick {})'


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


def check_fetch(var, url):
    """gateway.fetch path (api_key= parameter, rejected key retried once without it and named in keys-invalid.json)."""
    gw.jget(url)
    return 'refused' if var in sc.invalid_keys(gw.STATE) else 'ok'


def check(e):
    """[(label, ok, text)] for entry e, one minimal live request per source, in a temporary state dir (no cache, no stale token)."""
    var = e['vars'][0]
    if state(e) == 'absent':
        return [(l, False, f"not installed (run: python3 -I tools/setup_keys.py {e['name']})") for l in LABEL.get(var, [e.get('provider') or e['name']])]
    if not e['wired']: return [(e['name'], True, 'installed; no live check: VP does not use this key yet (engine not wired)')]
    with tempfile.TemporaryDirectory(prefix='vp-setup-') as tmp:
        gw.STATE = pathlib.Path(tmp)
        if e.get('provider'): return [(e['provider'], *check_provider(e))]
        if var == 'PISTE_CLIENT_ID': return check_piste()
        label = LABEL[var][0]
        try:
            if var == 'OPENALEX_KEY': r = check_fetch(var, 'https://api.openalex.org/works?per_page=1&select=id&search=test' + gw.oa_key())
            elif var == 'NCBI_API_KEY': r = check_fetch(var, 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmode=json&retmax=1&term=test' + gw.ncbi_key())
            elif var == 'VP_GITHUB_TOKEN':
                try: r = sc.CodeSearch(sc.CodeClient(cache_dir=tmp)).search('test', provider='github', limit=1); r = 'ok' if isinstance(r, list) else 'refused'
                except ValueError as x:
                    if str(x) not in ('credential_invalid', 'provider_error:HTTP401', 'provider_error:HTTP403'): raise
                    r = 'refused'
            elif var == 'SWH_TOKEN':
                sc.Provenance(sc.CodeClient(cache_dir=tmp)).origins('test', limit=1); r = 'refused' if var in sc.invalid_keys(tmp) else 'ok'
            elif var == 'FRED_API_KEY':
                x = gw.search_fred('unemployment', 1, gw.Barrier(dt.date.today()))[0]; r = 'refused' if isinstance(x, dict) and x.get('reason') == 'key_invalid' else 'ok'
            else: return [(label, True, 'installed; no live check for this key')]
        except Exception as x: return [(label, False, 'could not be checked: ' + why(x))]
        return [(label, True, 'OK')] if r == 'ok' else [(label, False, 'key refused — check you copied it whole')]


def check_piste():
    """The real PISTE engines: token by client credentials, then one search each (Judilibre GET /search, Legifrance POST /search, codes)."""
    B, out = gw.Barrier(dt.date.today()), []
    for label, run in (('Judilibre', lambda: gw.search_judilibre('contrat', 1, B)), ('Légifrance', lambda: gw.search_legifrance('contrat', 1, B, fund='code'))):
        try: r, note = run()
        except Exception as x: out.append((label, False, 'could not be checked: ' + why(x))); continue
        if isinstance(r, list): out.append((label, True, 'OK')); continue
        reason = r.get('reason')
        out.append((label, False, REFUSED['PISTE_CLIENT_ID'] if reason in ('key_invalid', 'credential_invalid') else SUBSCRIBE.format(label) if reason == 'not_subscribed'
                    else f'not checked ({reason})'))
    return out


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
    print(f"Get it here: {e['url']}" + (f" ({HINT[e['vars'][0]]})" if e['vars'][0] in HINT else ''))
    vals = []
    for v in e['vars']:
        x = ask(PROMPT.get(v, f'Paste {v}'))
        if not x: print(f'Nothing entered for {v}: nothing written.', file=sys.stderr); return 2
        if not re.fullmatch(r'[\x21-\x7e]+', x): print(f'{v}: the value contains spaces or unusual characters; copy it again (nothing written).', file=sys.stderr); return 2
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
