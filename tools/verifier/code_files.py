#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Code sources of the verifier (plugins/code.md, section "Verification", rule 1): a card source cited as `<path>@<SHA>` (field `code`
of the card's sources table, or a key / field `local:<path>@<SHA>` for the host code X) is read as the WHOLE FILE AT THAT SHA, never
the working copy, never an excerpt written by the engine:
  1. local git directories, in this order: the --repo directories given to verifier.py; X of the capsule (capsule.json
     `identity.repo`); the absolute paths named in capsule.json / capsule.md / scope.md (e.g. the bare mirror of Y supplied by the
     host); the nearest parent of the run directory holding .git (X = "the current directory", plugins/code.md). The first directory
     that holds the commit answers, through `git show` only: `git show -s <sha>^{commit}` (full SHA and commit date), then
     `git show <sha>:<path>` (the blob). No clone, no checkout, no hook, no textconv, no external diff, no pager, no fsmonitor, no
     system or global git config, no execution of any code of the repository; a symbolic link is read as its target text.
  2. otherwise, the gateway's code engine `provenance`, command `code-file <origin>#<path>@<40-hex SHA>` (Software Heritage, counted
     in the verifier's pool, date barrier = the commit date), when the card or the capsule gives the origin URL and the plugin declares
     the engine.
A branch name or a non-hexadecimal revision is refused (`unpinned`), never resolved; an absolute path or a `..` segment is refused.
Bound: the size bound of the code transport (code_sources.MAX_BYTES); a binary blob (NUL byte) is refused.
Standard library only. Import: code_ref(key, desc) ; run_repos(run_dir, given) ; read(ref, repos, gateway=None, origin=None)."""
import hashlib, json, os, pathlib, re, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import code_sources as _sc   # noqa: E402  (transport bound shared with the gateway's code engines)

MAX_BYTES = _sc.MAX_BYTES
REF = re.compile(r'(?P<path>[^\s@]+?)(?::(?P<line>\d+)(?:\s*[-–]\s*(?P<end>\d+))?)?@(?P<sha>[0-9a-fA-F]{7,40})')
ABS = re.compile(r'(?<![\w.:/])(/[^\s()`\'"<>,;\]\[*]+)')
TIMEOUT = 120


def code_ref(key, desc):
    """Source key + its entry of the card's sources table -> None (not a code source) | {'path', 'sha', 'line', 'end', 'side', 'ident'}
    | {'error': 'unpinned' | 'reference', 'ident'}. side: 'X' for `local:` (the host code), else 'Y'."""
    desc = desc or {}
    v = desc.get('code') or desc.get('local') or (key if str(key).startswith('local:') else None)
    if not v: return None
    v = str(v).strip(); local = v.startswith('local:') or bool(desc.get('local')) or str(key).startswith('local:')
    body = v[len('local:'):] if v.startswith('local:') else v
    m = REF.fullmatch(body)
    if not m: return {'error': 'unpinned' if '@' in body else 'reference', 'ident': v}
    path = m['path']
    if path.startswith('/') or any(x in ('', '.', '..') for x in path.split('/')): return {'error': 'reference', 'ident': v}
    return {'path': path, 'sha': m['sha'].lower(), 'line': int(m['line']) if m['line'] else None, 'end': int(m['end']) if m['end'] else None,
            'side': 'X' if local else 'Y', 'ident': v}


def git_dir(d):
    """Directory -> its git directory (working copy: d/.git, a directory or a gitfile; bare: d itself), else None. Never searched upwards."""
    d = pathlib.Path(d)
    if (d / '.git').exists(): return d / '.git'
    if (d / 'HEAD').is_file() and (d / 'objects').is_dir(): return d
    return None


def _env():
    return {'PATH': os.environ.get('PATH') or '/usr/bin:/bin', 'HOME': os.environ.get('HOME') or os.devnull, 'LC_ALL': 'C',
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_REPLACE_OBJECTS': '1',
            'GIT_OPTIONAL_LOCKS': '0', 'GIT_PAGER': 'cat', 'PAGER': 'cat', 'GIT_ATTR_NOSYSTEM': '1'}


def git_show(gd, *args):
    """`git show` read-only on the git directory gd: (rc, stdout bytes). Hooks, fsmonitor, textconv, external diff, signature check and pager
    disabled; system and global config ignored; command-line -c overrides the repository's own config."""
    cmd = ['git', '-c', 'core.hooksPath=' + os.devnull, '-c', 'core.fsmonitor=false', '-c', 'core.pager=cat', '-c', 'diff.external=', '-c', 'log.showSignature=false',
           '--git-dir=' + str(gd), 'show', '--no-textconv', '--no-ext-diff', '--no-color', *args]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT, env=_env(), stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return 1, b''
    return p.returncode, p.stdout


def _json(p):
    try: return json.loads(pathlib.Path(p).read_text(errors='replace'))
    except (OSError, ValueError): return {}


def run_repos(run_dir=None, given=()):
    """Local git directories to try, in order, each {'repo', 'from'}: --repo, capsule X, absolute paths of capsule.json / capsule.md /
    scope.md that are git directories, nearest parent of the run directory holding .git. Duplicates (same resolved path) dropped."""
    cands = [(g, '--repo') for g in given or ()]
    if run_dir:
        run = pathlib.Path(run_dir)
        cap = _json(run / 'capsule.json')
        ident = cap.get('identity') if isinstance(cap.get('identity'), dict) else {}
        if ident.get('repo'): cands.append((ident['repo'], 'capsule.json identity.repo (X)'))
        y = cap.get('Y') if isinstance(cap.get('Y'), dict) else {}
        for k in ('local', 'repo_dir', 'mirror'):
            if y.get(k): cands.append((y[k], f'capsule.json Y.{k}'))
        for m in ABS.finditer(str(y.get('sha_source') or '')): cands.append((m.group(1), 'capsule.json Y.sha_source'))
        for name in ('capsule.md', 'scope.md'):
            f = run / name
            if f.is_file():
                for m in ABS.finditer(f.read_text(errors='replace')): cands.append((m.group(1).rstrip('.:'), name))
        for d in [run.resolve(), *run.resolve().parents]:
            if (d / '.git').exists(): cands.append((str(d), 'nearest parent of the run holding .git')); break
    out, seen = [], set()
    for d, why in cands:
        try: p = pathlib.Path(d).resolve()
        except (OSError, RuntimeError): continue
        if p in seen or not p.is_dir() or not git_dir(p): continue
        seen.add(p); out.append({'repo': str(p), 'from': why})
    return out


def read_local(ref, repos):
    """-> (text, receipt) from the first repository holding the commit, or (None, {'tried': [...], 'reason'})."""
    tried = []
    for r in repos:
        gd = git_dir(r['repo'])
        rc, out = git_show(gd, '-s', '--format=%H%x09%cI', ref['sha'] + '^{commit}', '--')
        if rc or not out.strip():
            tried.append(r['repo']); continue
        full, date = out.decode('ascii', 'replace').strip().split('\t')[:2]
        spec = f"{full}:{ref['path']}"
        rc, data = git_show(gd, spec)
        base = {'method': 'git show', 'repo': r['repo'], 'repo_from': r['from'], 'commit': full, 'commit_date': date, 'path': ref['path']}
        if rc: return None, dict(base, reason=f"file absent at the SHA ({ref['path']}@{full[:12]})")
        if data.startswith(f'tree {spec}\n'.encode()): return None, dict(base, reason=f"a directory, not a file, at the SHA ({ref['path']})")
        if len(data) > MAX_BYTES: return None, dict(base, reason=f'file larger than the code transport bound ({MAX_BYTES} bytes)')
        if b'\0' in data: return None, dict(base, reason='binary file')
        return data.decode('utf-8', 'replace'), dict(base, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    return None, {'tried': tried, 'reason': (f"commit {ref['sha'][:12]} not found in the local git directories ({len(tried)} tried)" if tried
                                             else 'no local git directory (capsule, scope.md, --repo)')}


def origin_of(ref, desc, run_dir=None):
    """Origin URL for the gateway: the card's url/repo field when it is https, else for Y the repository of the capsule (github.com/o/r)."""
    for k in ('url', 'repo', 'origin'):
        v = str((desc or {}).get(k) or '')
        m = re.match(r'(https://[A-Za-z0-9.-]+/[^\s#/]+/[^\s#/]+?)(?:\.git)?(?:/|$)', v)
        if m: return m.group(1)
        if re.fullmatch(r'[A-Za-z0-9.-]+\.[a-z]+/[\w.-]+/[\w.-]+', v): return 'https://' + v.removesuffix('.git')
    if ref.get('side') == 'Y' and run_dir:
        y = _json(pathlib.Path(run_dir) / 'capsule.json').get('Y')
        v = str((y or {}).get('repo') or '') if isinstance(y, dict) else ''
        if re.fullmatch(r'[A-Za-z0-9.-]+\.[a-z]+/[\w.-]+/[\w.-]+', v): return 'https://' + v.removesuffix('.git')
    return None


def read(ref, repos, gateway=None, origin=None):
    """-> (text | None, receipt). Local git directories first, then the gateway (code-file) when an origin and a 40-hex SHA are known."""
    if ref.get('error'): return None, {'reason': f"{ref['error']}: {ref['ident']} (a code source is cited <path>@<SHA>, SHA in hexadecimal)"}
    text, rec = read_local(ref, repos)
    if text is not None or rec.get('commit'): return text, rec           # the commit was found locally: its answer stands
    if gateway is None or not origin: return None, rec
    sha = ref['sha']
    if len(sha) != 40: return None, dict(rec, reason=rec['reason'] + '; gateway not tried: abbreviated SHA')
    res = gateway.call('code-file', f"{origin}#{ref['path']}@{sha}")
    r = res.get('results') if isinstance(res, dict) else None
    if isinstance(r, dict) and isinstance(r.get('text'), str) and r['text'].strip():
        return r['text'], {'method': 'gateway code-file (provenance)', 'origin': origin, 'commit': sha, 'commit_date': r.get('date'), 'path': ref['path'],
                           'swhid': r.get('swhid'), 'bytes': r.get('bytes'), 'sha256': r.get('sha256'), 'call': res.get('call')}
    why = (res.get('refusal') or (r or {}).get('refusal') or (r or {}).get('error') or 'no text') if isinstance(res, dict) else 'no answer'
    return None, dict(rec, reason=rec['reason'] + f'; gateway code-file: {why}')
