#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Whole-reading digest of a bare git repository at a SHA, gitingest-style, without any LLM and without executing a single line
of the repository. Standard library only; git read-only (`ls-tree`, `cat-file`): no checkout, no clone.

Output (text): header, full tree (each file: bytes, included / not included and why), then the retained text files in full,
each under `=== <path> @<sha12> (<n> lines) ===` with line numbers (`N<TAB>text`).

Rules, all declared here (no decision taken from the content):
- excluded: binary files (NUL byte in the first 8,000 bytes or image/sound/video/font/archive extension),
  lockfiles (package-lock.json, pnpm-lock.yaml, yarn.lock, bun.lock*, Cargo.lock, poetry.lock, uv.lock, Gemfile.lock, composer.lock),
  any path containing `node_modules/`, and the prefixes given with `--exclude` (interface tests, interface directories);
- order: the prefixes of `--priority`, in the given order (then alphabetical path inside each prefix); files without a priority
  prefix come after, alphabetical;
- cap: `--cap` characters (files only, tree and header excluded); a file that no longer fits is marked
  "not included (cap)" and the next ones are tried (first that fits, in order); a file is never truncated.

Usage: condense_repo.py --repo <dir.git> --sha <sha> --name <owner/repo> --out <file> [--cap 400000]
                        [--priority README.md LICENSE.md agent/ ...] [--exclude tests/ components/ ...]
"""
import argparse, json, pathlib, subprocess, sys

EXT_BIN = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.icns', '.bmp', '.svg', '.mp4', '.mp3', '.wav', '.mov', '.webm',
           '.woff', '.woff2', '.ttf', '.otf', '.eot', '.zip', '.gz', '.tar', '.tgz', '.bz2', '.xz', '.7z', '.pdf', '.pyc', '.so', '.dylib',
           '.dll', '.exe', '.bin', '.wasm', '.jar', '.class', '.lockb', '.db', '.sqlite'}
LOCKFILES = {'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock', 'bun.lock', 'bun.lockb', 'Cargo.lock', 'poetry.lock', 'uv.lock',
             'Gemfile.lock', 'composer.lock', 'Pipfile.lock', 'flake.lock'}

def git(repo, *args):
    p = subprocess.run(['git', '--git-dir', repo, *args], capture_output=True, timeout=300)
    if p.returncode: raise SystemExit('git ' + ' '.join(args[:2]) + ': ' + p.stderr.decode('utf-8', 'replace')[:300])
    return p.stdout

def tree(repo, sha):
    rows = []
    for l in git(repo, 'ls-tree', '-r', '-l', sha).decode('utf-8', 'replace').splitlines():
        meta, _, path = l.partition('\t'); parts = meta.split()
        if len(parts) >= 4 and parts[1] == 'blob': rows.append((path, int(parts[3]) if parts[3].isdigit() else 0, parts[2]))
    return rows

def exclusion_reason(path, exclude):
    name = path.rsplit('/', 1)[-1]; ext = ('.' + name.rsplit('.', 1)[-1].lower()) if '.' in name else ''
    if 'node_modules/' in path or path.startswith('node_modules'): return 'node_modules'
    if name in LOCKFILES: return 'lockfile'
    if ext in EXT_BIN: return 'binary (extension)'
    for e in exclude:
        if path.startswith(e) or ('/' + e) in ('/' + path): return 'excluded (' + e + ')'
    return None

def rank(path, priority):
    for i, p in enumerate(priority):
        if path == p or path.startswith(p): return (i, path)
    return (len(priority), path)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--repo', required=True); ap.add_argument('--sha', required=True); ap.add_argument('--name', required=True)
    ap.add_argument('--out', required=True); ap.add_argument('--cap', type=int, default=400000)
    ap.add_argument('--priority', nargs='*', default=[]); ap.add_argument('--exclude', nargs='*', default=[])
    a = ap.parse_args()
    sha = git(a.repo, 'rev-parse', a.sha + '^{commit}').decode().strip(); s12 = sha[:12]
    rows = tree(a.repo, sha)
    state = {}  # path -> exclusion reason or None
    for path, nbytes, blob in rows: state[path] = exclusion_reason(path, a.exclude)
    order = sorted((r for r in rows if state[r[0]] is None), key=lambda r: rank(r[0], a.priority))
    kept = []; total = 0
    for path, nbytes, blob in order:
        data = git(a.repo, 'cat-file', 'blob', blob)
        if b'\0' in data[:8000]: state[path] = 'binary (NUL)'; continue
        try: text = data.decode('utf-8')
        except UnicodeDecodeError: state[path] = 'not UTF-8'; continue
        if total + len(text) > a.cap: state[path] = 'not included (cap)'; continue
        total += len(text); kept.append((path, text)); state[path] = 'included'
    out = [f'# Y = {a.name}@{s12}: whole-reading digest (no LLM): full tree then {len(kept)} whole text files, '
           f'{total} characters (cap {a.cap}); files not included are marked in the tree with the reason.',
           f'# Expected citation: <path>:<line>@{s12}', '', f'## Tree ({len(rows)} files, bytes, state)']
    for path, nbytes, blob in rows: out.append(f'{nbytes:>9}  {path}  [{state[path]}]')
    out += ['', '## Files (whole, numbered)', '']
    for path, text in kept:
        lines = text.splitlines()
        out.append(f'=== {path} @{s12} ({len(lines)} lines) ===')
        out += [f'{i}\t{l}' for i, l in enumerate(lines, 1)]; out.append('')
    pathlib.Path(a.out).write_text('\n'.join(out) + '\n')
    summary = dict(repo=a.name, sha=sha, tree_files=len(rows), included=len(kept), chars_files=total, chars_total=sum(len(l) + 1 for l in out),
                   cap=a.cap, priority=a.priority, exclude=a.exclude,
                   reasons={r: sum(1 for v in state.values() if v == r) for r in sorted(set(state.values()))},
                   not_included_cap=[p for p, v in state.items() if v == 'not included (cap)'])
    print(json.dumps(summary, ensure_ascii=False, indent=1))

if __name__ == '__main__': main()
