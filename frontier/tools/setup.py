#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bootstrap and self-check of the Frontier skill (README, "Install"). Standard library only; macOS and Linux.

What it does:
  1. Python: 3.9 or later is required (exit code 2 otherwise).
  2. Skill-local virtual environment: frontier/.venv is created ONLY when frontier/requirements.txt lists packages
     (none in this version: nothing is created). When it is created, pip installs those packages inside frontier/.venv,
     which downloads them from the package index: the output says so. Nothing is ever installed outside the skill directory;
     "installed_outside_skill" lists what was (always empty).
  3. VanishingPoint (optional dependency): --vp-dir, else the environment variable FRONTIER_VP_DIR, else "vp_dir" of
     frontier/config.json, else the parent directory of frontier/ (the VP repository layout); a directory counts as VP when
     its SKILL.md front matter says `name: vanishingpoint`. An explicit --vp-dir or FRONTIER_VP_DIR is authoritative:
     if invalid (including empty), VP is not found and no configured or sibling fallback is tried;
     an empty explicit path is a usage error (exit 2).
  4. Container engine (optional, for tools/run_test.py): docker, else podman, on PATH; the daemon answers `version`; the
     probe image of config.json ("probe_image") is present locally (never pulled: pull it yourself if you want execution);
     then one `run --rm --network none --pull=never <probe image> true` checks that a network-less container starts.
     Frontier never installs an engine: install Docker Desktop, Docker Engine or Podman yourself if you want execution.
  5. Reports the critic families, host family and search model configured (config.json "critic" and "search_model",
     or FRONTIER_CRITIC_FAMILIES, FRONTIER_HOST_FAMILY, FRONTIER_SEARCH_MODEL) and the budget per idea.
--check: read-only (creates nothing, still runs the engine probe, which writes nothing in the skill directory).
--json: one JSON object on stdout instead of the human summary.

Usage: setup.py [--check] [--json] [--vp-dir DIR]
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # --check stays read-only: no __pycache__ written in the skill directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

FRONTIER = Path(__file__).resolve().parent.parent
MIN_PY = (3, 9)
ENGINES = ('docker', 'podman')


def config():
    try:
        return json.loads((FRONTIER / 'config.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def requirements():
    p = FRONTIER / 'requirements.txt'
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text(encoding='utf-8').splitlines() if l.strip() and not l.strip().startswith('#')]


def is_vp(d):
    try:
        text = (Path(d) / 'SKILL.md').read_text(encoding='utf-8')
    except OSError:
        return False
    m = re.match(r'^---\s*\n(.*?)\n---', text, re.S)
    return bool(m and re.search(r'(?m)^name:\s*vanishingpoint\s*$', m.group(1)))


def detect_vp(cli_dir=None):
    notes = []
    env_dir = os.environ.get('FRONTIER_VP_DIR')
    if cli_dir is not None:
        candidates = [('cli', cli_dir)]
    elif env_dir is not None:
        candidates = [('env', env_dir)]
    else:
        candidates = [('config', config().get('vp_dir')), ('sibling', str(FRONTIER.parent))]
    for how, d in candidates:
        if not d:
            if how in ('cli', 'env'):
                notes.append('%s VP path is empty' % how)
            continue
        p = Path(d).expanduser()
        if is_vp(p):
            return {'found': True, 'dir': str(p.resolve()), 'how': how, 'notes': notes}
        if how != 'sibling':
            notes.append('%s VP path %s has no SKILL.md with name: vanishingpoint' % (how, p))
    return {'found': False, 'dir': None, 'how': None, 'notes': notes}


def _run(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return r.returncode, (r.stdout + r.stderr).strip()[-300:]
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)[-300:]


def detect_engine():
    probe = config().get('probe_image') or 'busybox:latest'
    out = {'name': None, 'path': None, 'daemon': None, 'network_none': 'untested', 'probe_image': probe, 'detail': ''}
    for name in ENGINES:
        exe = shutil.which(name)
        if exe:
            out['name'], out['path'] = name, exe
            break
    if not out['path']:
        out['detail'] = 'no docker or podman on PATH: tests are delivered as plans ("plan only")'
        return out
    exe = out['path']
    if not common.config().get('execution_enabled', False):   # common.config() honours FRONTIER_EXECUTION_ENABLED=1
        out['detail'] = ('%s found, but execution is disabled in this release (config.json "execution_enabled": false): '
                         'no probe container is started; tests are delivered as plans' % out['name'])
        return out
    code, msg = _run([exe, 'version'], 30)
    out['daemon'] = 'ok' if code == 0 else 'unreachable'
    if code != 0:
        out['detail'] = '%s is installed but does not answer `version` (daemon or machine not running): %s' % (out['name'], msg)
        return out
    code, msg = _run([exe, 'image', 'inspect', probe], 30)
    if code != 0:
        out['detail'] = ('probe image %s is not present locally; Frontier never pulls images: run `%s pull %s` yourself '
                         'to enable execution' % (probe, out['name'], probe))
        return out
    code, msg = _run([exe, 'run', '--rm', '--network', 'none', '--pull=never', probe, 'true'], 120)
    out['network_none'] = 'ok' if code == 0 else 'failed'
    out['detail'] = ('a container without network starts' if code == 0
                     else 'a container with --network none did not start: %s' % msg)
    return out


def venv_status(check):
    path = FRONTIER / '.venv'
    reqs = requirements()
    st = {'path': str(path), 'needed': bool(reqs), 'exists': path.exists(), 'packages': reqs, 'action': ''}
    if not reqs:
        st['action'] = 'not needed (requirements.txt lists no package)'
    elif path.exists():
        st['action'] = 'exists'
    elif check:
        st['action'] = 'would create %s and pip-install %d package(s) into it (download from the package index)' % (
            path, len(reqs))
    else:
        import venv
        venv.create(str(path), with_pip=True)
        py = path / ('Scripts' if os.name == 'nt' else 'bin') / ('python.exe' if os.name == 'nt' else 'python')
        code, msg = _run([str(py), '-m', 'pip', 'install', '-r', str(FRONTIER / 'requirements.txt')], 600)
        st['exists'] = True
        st['action'] = 'created; pip install %s' % ('ok' if code == 0 else 'FAILED: ' + msg)
    return st


def report(check=False, vp_dir=None):
    ok = sys.version_info[:2] >= MIN_PY
    rep = {
        'frontier_dir': str(FRONTIER), 'platform': platform.system(),
        'python': {'version': platform.python_version(), 'executable': sys.executable, 'ok': ok,
                   'required': '%d.%d' % MIN_PY},
        'check_only': check,
    }
    rep['venv'] = venv_status(check) if ok else {'path': str(FRONTIER / '.venv'), 'needed': False, 'exists': False,
                                                 'action': 'skipped (Python too old)'}
    vp = detect_vp(vp_dir)
    notes = vp.pop('notes')
    rep['vp'] = vp
    rep['engine'] = detect_engine()
    rep['execution_available'] = rep['engine']['network_none'] == 'ok'
    cfg = common.config()
    rep['critic'] = {k: cfg['critic'].get(k) for k in ('host_family', 'families')}
    rep['search_model'] = cfg.get('search_model')
    rep['budget'] = cfg['budget']
    rep['installed_outside_skill'] = []
    if not vp['found']:
        notes.append('VP not found: prior art uses the host search and every card starts with '
                     '"References not verified (VP not installed)"')
    if not rep['execution_available']:
        notes.append('no isolated execution: step 5 writes result.json {"mode": "plan only"}')
    rep['notes'] = notes
    return rep


def human(rep):
    lines = ['Frontier setup (%s)%s' % (rep['frontier_dir'], ' [check only]' if rep['check_only'] else '')]
    py = rep['python']
    lines.append('Python %s: %s' % (py['version'], 'ok' if py['ok'] else 'TOO OLD (need %s)' % py['required']))
    lines.append('Skill venv: %s' % rep['venv']['action'])
    vp = rep['vp']
    lines.append('VP: %s' % ('found at %s (%s)' % (vp['dir'], vp['how']) if vp['found'] else 'not found'))
    e = rep['engine']
    lines.append('Container engine: %s; network none: %s; %s' % (e['name'] or 'none', e['network_none'], e['detail']))
    lines.append('Execution available: %s' % ('yes' if rep['execution_available'] else 'no (plan only)'))
    c = rep['critic']
    lines.append('Critic families configured: %s; host family: %s; search model: %s' % (
        ', '.join(c['families']) or 'none (same-family critique, declared as such)', c['host_family'] or 'not set',
        rep['search_model'] or 'host default'))
    lines.append('Installed outside the skill directory: nothing')
    lines.extend('note: ' + n for n in rep['notes'])
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--vp-dir')
    a = ap.parse_args(argv)
    if a.vp_dir == '' or (a.vp_dir is None and os.environ.get('FRONTIER_VP_DIR') == ''):
        ap.error('VP path must not be empty (--vp-dir / FRONTIER_VP_DIR)')
    rep = report(a.check, a.vp_dir)
    print(json.dumps(rep, indent=2) if a.json else human(rep))
    return 0 if rep['python']['ok'] else 2


if __name__ == '__main__':
    sys.exit(main())
