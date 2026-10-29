#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Automatic update of the skill to its latest published release (standard library, git). Run by `check_keys.py --announce` at the
start of a run, at most once per `update.interval_hours` (tools/config.json); prints at most ONE factual line, never an instruction:
  "VanishingPoint updated 0.6.6 -> 0.6.7 (takes effect at the next run)"
  "VanishingPoint 0.6.7 available (installed 0.6.6): git -C <dir> pull"      (notice: update off, or update refused)
Latest version = the highest tag vX.Y.Z (update.tag_pattern) of the public repository (update.remote, empty = the `repository` of
.claude-plugin/plugin.json), read with `git ls-remote --tags`, never a branch, no credential, nothing sent. Only when strictly higher
than the installed `version`. With the option on: `git fetch` of that tag, then a fast-forward only, git hooks disabled, no script run.
Refused (notice line only) when tracked files are modified, the branch has diverged, the skill directory is not the top of its own git
repository (copy managed by a plugin system, archive...), VP_OFFLINE=1 (the last version seen online is used), or git fails or times out
(update.timeout_s). Any error prints nothing. The option: update.auto (false by default), overridden by the user's answer to
`--setup` stored in ~/.config/vp/update.json; update.notify = false silences the notice.
Usage: auto_update.py --setup     ask "Update VanishingPoint automatically? [Y/n]" and store the answer
       auto_update.py [--now]     check now (--now: ignore the once-a-day limit)
Import: run(root=None, home=None, cfg=None, now=None, force=False) -> str (the line or ''). Exit code: 0 (2 for a usage error)."""
import argparse, datetime as dt, json, os, pathlib, re, subprocess, sys, tempfile
P = pathlib.Path(__file__).resolve().parent
ROOT = P.parent


def load_cfg():
    try: return json.loads((P / 'config.json').read_text(encoding='utf-8')).get('update') or {}
    except (OSError, ValueError): return {}


def config_dir(cfg, home=None):
    return pathlib.Path(home or pathlib.Path.home()) / cfg['config_dir']


def read_json(path):
    try:
        d = json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError): return {}


def write_json(path, data):
    """Atomic write; False when the directory is not writable."""
    path = pathlib.Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '.')
        with os.fdopen(fd, 'w', encoding='utf-8') as w: w.write(json.dumps(data, indent=1) + '\n')
        os.replace(tmp, path); return True
    except OSError: return False


def choice(cfg, home=None):
    """(auto, notify): the user's stored answer wins over tools/config.json."""
    c = read_json(config_dir(cfg, home) / cfg['choice_file'])
    auto = c['auto'] if isinstance(c.get('auto'), bool) else bool(cfg.get('auto', False))
    notify = c['notify'] if isinstance(c.get('notify'), bool) else bool(cfg.get('notify', True))
    return auto, notify


def version_tuple(v):
    m = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)', str(v or '').strip())
    return tuple(int(x) for x in m.groups()) if m else None


def fmt(t): return '.'.join(map(str, t))


def manifest(root, cfg):
    return read_json(pathlib.Path(root) / cfg['manifest'])


def git(args, cwd=None, timeout=5):
    """git with no prompt, no credential helper, hooks disabled; (returncode, stdout). Raises OSError / TimeoutExpired."""
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env['GIT_TERMINAL_PROMPT'] = '0'
    cmd = ['git', '-c', 'core.hooksPath=' + os.devnull, '-c', 'credential.helper=', '-c', 'core.fsmonitor=false'] + list(args)
    p = subprocess.run(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout


def latest_remote(url, cfg):
    """(version tuple, tag name) of the highest release tag of the remote, or None."""
    rc, out = git(['ls-remote', '--tags', '--refs', url], timeout=cfg['timeout_s'])
    if rc != 0: return None
    pat, best = re.compile(cfg['tag_pattern']), None
    for line in out.splitlines():
        ref = line.split('\t', 1)[-1].strip()
        if not ref.startswith('refs/tags/'): continue
        tag = ref[len('refs/tags/'):]
        m = pat.fullmatch(tag)
        if m:
            v = tuple(int(x) for x in m.groups())
            if best is None or v > best[0]: best = (v, tag)
    return best


def own_repo(root, cfg):
    """True when root is the top of its own git work tree (not a directory inside a larger repository)."""
    rc, out = git(['-C', str(root), 'rev-parse', '--show-toplevel'], timeout=cfg['timeout_s'])
    return rc == 0 and out.strip() and pathlib.Path(out.strip()).resolve() == pathlib.Path(root).resolve()


def fast_forward(root, url, tag, target, cfg):
    """Fetch the tag and fast-forward to it. True on success; False = refused (left unchanged)."""
    t, r = cfg['timeout_s'], str(root)
    rc, out = git(['-C', r, 'status', '--porcelain', '--untracked-files=no'], timeout=t)
    if rc != 0 or out.strip(): return False                                  # tracked files modified locally
    rc, _ = git(['-C', r, 'fetch', '--quiet', '--no-tags', '--no-recurse-submodules', url, 'refs/tags/' + tag], timeout=t)
    if rc != 0: return False
    rc, sha = git(['-C', r, 'rev-parse', '--verify', '--quiet', 'FETCH_HEAD^{commit}'], timeout=t)
    sha = sha.strip()
    if rc != 0 or not re.fullmatch(r'[0-9a-f]{40,64}', sha): return False
    rc, man = git(['-C', r, 'show', sha + ':' + cfg['manifest']], timeout=t)       # the release must carry the version of its tag
    try: tagged = version_tuple(json.loads(man).get('version')) if rc == 0 else None
    except ValueError: tagged = None
    if tagged != target: return False
    rc, _ = git(['-C', r, 'merge-base', '--is-ancestor', 'HEAD', sha], timeout=t)
    if rc != 0: return False                                                 # diverged (or HEAD ahead of the release)
    rc, _ = git(['-C', r, 'merge', '--ff-only', '--quiet', '--no-edit', '--no-stat', sha], timeout=t)
    return rc == 0


def run(root=None, home=None, cfg=None, now=None, force=False):
    """The line to print ('' = nothing). Never raises for an expected failure (git missing, network, timeout, bad files)."""
    root = pathlib.Path(root or ROOT); cfg = cfg if cfg is not None else load_cfg()
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        state_file = config_dir(cfg, home) / cfg['state_file']
        state = read_json(state_file)
        try: last = dt.datetime.fromisoformat(state.get('checked', ''))
        except (TypeError, ValueError): last = None
        if last is not None and last.tzinfo is None: last = None
        if not force and last is not None and dt.timedelta(0) <= now - last < dt.timedelta(hours=float(cfg['interval_hours'])): return ''
        man = manifest(root, cfg); installed = version_tuple(man.get('version'))
        url = (cfg.get('remote') or '').strip() or str(man.get('repository') or '').strip()
        if installed is None or not url: return ''
        offline = os.environ.get('VP_OFFLINE') == '1'
        state['checked'] = now.isoformat(timespec='seconds')
        if not write_json(state_file, state): return ''                       # no writable cache: never check at every run
        found = None
        if not offline:
            try: found = latest_remote(url, cfg)
            except (OSError, subprocess.SubprocessError): found = None
        if found:
            state['latest'], state['latest_tag'] = fmt(found[0]), found[1]; write_json(state_file, state)
        else:
            v = version_tuple(state.get('latest'))
            found = (v, state.get('latest_tag')) if v else None
            offline = True                                                   # no fresh answer: notice only, never an update
        if not found or found[0] <= installed: return ''
        auto, notify = choice(cfg, home)
        label, target, tag = cfg['label'], found[0], found[1]
        managed = any(m in str(root.resolve()) for m in cfg.get('managed_path_markers') or [])
        is_repo = False
        if not managed:
            try: is_repo = bool(own_repo(root, cfg))
            except (OSError, subprocess.SubprocessError): is_repo = False
        if auto and is_repo and not offline and tag:
            try: ok = fast_forward(root, url, tag, target, cfg)
            except (OSError, subprocess.SubprocessError): ok = False
            if ok: return f'{label} updated {fmt(installed)} -> {fmt(target)} (takes effect at the next run)'
        if not notify: return ''
        return f'{label} {fmt(target)} available (installed {fmt(installed)})' + (f': git -C {root} pull' if is_repo else '')
    except Exception:                                                        # never break the host tool
        return ''


def setup(cfg=None, home=None):
    """Ask once (default yes) and store {"auto": bool} next to the keys. Returns the stored value."""
    cfg = cfg if cfg is not None else load_cfg()
    q = f"Update {cfg['label']} automatically? [Y/n] "
    if sys.stdin.isatty():
        try: a = input(q).strip().lower()
        except EOFError: a = ''
    else:
        print(q, flush=True); a = sys.stdin.readline().strip().lower()
    auto = a not in ('n', 'no', 'non')
    f = config_dir(cfg, home) / cfg['choice_file']
    c = read_json(f); c['auto'] = auto
    if not write_json(f, c): print(f'auto_update.py: cannot write {f}', file=sys.stderr); return None
    print(f"Automatic update: {'on' if auto else 'off'} (stored in {f}; change it with --setup).")
    return auto


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--setup', action='store_true', help='ask whether to update automatically and store the answer')
    ap.add_argument('--now', action='store_true', help='check now, ignoring the once-a-day limit')
    a = ap.parse_args(argv)
    if a.setup: setup(); return 0
    line = run(force=a.now)
    if line: print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
