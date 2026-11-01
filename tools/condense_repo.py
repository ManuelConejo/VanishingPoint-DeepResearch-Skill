#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Whole-reading digest of a bare git repository at a SHA, gitingest-style, without any LLM and without executing a single line
of the repository. Standard library only; git read-only (`ls-tree`, `cat-file`): no checkout, no clone.

Output (text): header, full tree (each file: bytes, included / not included and why), then the retained text files in full,
each under `=== <path> @<sha40> (<n> lines) ===` with line numbers (`N<TAB>text`) counted as git and GitHub count them (split on \n only,
verifier/code_files.git_lines: a form feed, a lone \r or U+2028 never starts a line), so that a reference `<path>:<line>@<sha40>` written
from the digest is the one the verifier and the gateway read.

Rules, all declared here (no decision taken from the content):
- excluded: binary files (NUL byte in the first 8,000 bytes or image/sound/video/font/archive extension),
  lockfiles (package-lock.json, pnpm-lock.yaml, yarn.lock, bun.lock*, Cargo.lock, poetry.lock, uv.lock, Gemfile.lock, composer.lock),
  any path containing `node_modules/`, and the prefixes given with `--exclude` (interface tests, interface directories);
- order: the prefixes of `--priority`, in the given order; then, inside each group and for the files without a priority prefix, the
  default tiers of config.json whole_reading.default_order (root README / LICENCE / manifest files first, then the code, then the
  directories of documentation, tests, examples, benchmarks and CI), then alphabetical path;
- a file that is not UTF-8 is decoded as whole_reading.fallback_encoding (marked "included (decoded as <encoding>)") instead of being dropped;
- selection (config.json condense.selection, `--selection`): "order" (default) = the order above; "repo-map" = inside each priority group and
  each default tier, the files are ordered by decreasing score of a repository map (tools/repo_map.py: tags definition / reference per file,
  file graph weighted by the references to identifiers, PageRank personalised on the files and identifiers named by `--run`, i.e. scope.md,
  searches/*.md, capsule.md), then alphabetical path. Only the order changes: the files stay whole, the cap rule is the same;
- cap: `--cap` characters (files only, tree and header excluded); a file that no longer fits is marked
  "not included (cap)" and the next ones are tried (first that fits, in order); a file is never truncated.

Usage: condense_repo.py --repo <dir.git> --sha <sha> --name <owner/repo> --out <file> [--cap 400000]
                        [--priority README.md LICENSE.md agent/ ...] [--exclude tests/ components/ ...]
                        [--selection order|repo-map] [--run RUN_DIR (mentions for repo-map)]
Import: condense(reader, sha, name, cap, priority, exclude, selection=None, mentions=None) -> (text, summary); reader = LocalRepo(dir) (git -C, read-only commands) or
SnapshotRepo(snapshot, snap) (a bare one-commit snapshot of tools/repo_snapshot.py, read with its guarded git: no configuration, no hook,
no filter; used by whole_reading.py --y-gateway, no local mirror needed).
"""
import argparse, json, pathlib, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE / 'verifier'))
from code_files import git_lines   # noqa: E402  (line numbering of git and GitHub, shared with the verifier)

WR = json.loads((HERE / 'config.json').read_text()).get('whole_reading', {})
ORDER = WR.get('default_order') or {}
SELECTIONS = ('order', 'repo-map')
DEFAULT_SELECTION = (json.loads((HERE / 'config.json').read_text()).get('condense') or {}).get('selection') or 'order'
FALLBACK_ENCODING = WR.get('fallback_encoding') or 'latin-1'
EXT_BIN = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.icns', '.bmp', '.svg', '.mp4', '.mp3', '.wav', '.mov', '.webm',
           '.woff', '.woff2', '.ttf', '.otf', '.eot', '.zip', '.gz', '.tar', '.tgz', '.bz2', '.xz', '.7z', '.pdf', '.pyc', '.so', '.dylib',
           '.dll', '.exe', '.bin', '.wasm', '.jar', '.class', '.lockb', '.db', '.sqlite'}
LOCKFILES = {'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock', 'bun.lock', 'bun.lockb', 'Cargo.lock', 'poetry.lock', 'uv.lock',
             'Gemfile.lock', 'composer.lock', 'Pipfile.lock', 'flake.lock'}


class LocalRepo:
    """A local git directory (bare or not), read-only commands only (rev-parse, ls-tree, cat-file)."""
    def __init__(self, repo): self.repo = repo

    def git(self, *args):
        p = subprocess.run(['git', '-C', self.repo, *args], capture_output=True, timeout=300)
        if p.returncode: raise SystemExit('git ' + ' '.join(args[:2]) + ': ' + p.stderr.decode('utf-8', 'replace')[:300])
        return p.stdout

    def resolve(self, sha): return self.git('rev-parse', sha + '^{commit}').decode().strip()

    def tree(self, sha):
        rows = []
        for rec in self.git('ls-tree', '-r', '-l', '-z', sha).split(b'\0'):
            meta, _, path = rec.decode('utf-8', 'replace').partition('\t'); parts = meta.split()
            if len(parts) >= 4 and parts[1] == 'blob': rows.append((path, int(parts[3]) if parts[3].isdigit() else 0))
        return rows

    def blob(self, sha, path): return self.git('cat-file', 'blob', sha + ':' + path)


class SnapshotRepo:
    """A bare one-commit snapshot (tools/repo_snapshot.Snapshot.ensure), read with the snapshot's guarded git only."""
    def __init__(self, snapshot, snap, max_bytes):
        self.s, self.snap, self.max_bytes = snapshot, snap, max_bytes

    def resolve(self, sha): return sha

    def tree(self, sha):
        t = self.s.ls(self.snap, sha)
        if t['truncated']: raise SystemExit('snapshot tree over repo_grep.ls_paths_scanned entries: give --priority / --exclude or a local mirror')
        return [(f['path'], f['bytes'] or 0) for f in t['files']]

    def blob(self, sha, path): return self.s.show(self.snap, sha, path, self.max_bytes)


def exclusion_reason(path, exclude):
    name = path.rsplit('/', 1)[-1]; ext = ('.' + name.rsplit('.', 1)[-1].lower()) if '.' in name else ''
    if 'node_modules/' in path or path.startswith('node_modules'): return 'node_modules'
    if name in LOCKFILES: return 'lockfile'
    if ext in EXT_BIN: return 'binary (extension)'
    for e in exclude:
        if path.startswith(e) or ('/' + e) in ('/' + path): return 'excluded (' + e + ')'
    return None


def tier(path):
    """Default tier (config.json whole_reading.default_order): 0 = a root file named in first_root_files (or starting with one of
    first_root_prefixes: README, LICENSE, COPYING...), 2 = a path with a directory segment in last_dirs (docs, tests, examples...), else 1."""
    segs = path.split('/'); name = segs[-1]
    if len(segs) == 1 and (name in (ORDER.get('first_root_files') or ()) or
                           any(name.upper().startswith(p.upper()) for p in ORDER.get('first_root_prefixes') or ())): return 0
    last = {d.lower() for d in ORDER.get('last_dirs') or ()}
    return 2 if any(s.lower() in last for s in segs[:-1]) else 1


def rank(path, priority, scores=None):
    """Sort key. scores (repo-map selection): inside a priority group and a tier, decreasing score before the alphabetical path."""
    s = () if scores is None else (-scores.get(path, 0.0),)
    for i, p in enumerate(priority):
        if path == p or path.startswith(p): return (i, tier(path)) + s + (path,)
    return (len(priority), tier(path)) + s + (path,)


def condense(reader, sha, name, cap, priority=(), exclude=(), selection=None, mentions=None, repo_params=None):
    """-> (digest text, summary dict). sha: resolved by the reader; every citation header carries the full 40-hex SHA.
    selection: "order" (default of config condense.selection) or "repo-map"; mentions: {"idents": [...], "paths": [...]} to personalise it;
    repo_params: overrides of config condense.repo_map (the duel script varies size_exponent)."""
    selection = selection or DEFAULT_SELECTION
    if selection not in SELECTIONS: raise SystemExit(f'selection {selection!r}: expected one of {", ".join(SELECTIONS)}')
    sha = reader.resolve(sha)
    rows = reader.tree(sha)
    state = {path: exclusion_reason(path, exclude) for path, _ in rows}   # path -> exclusion reason or None
    scores = None; map_stats = None
    if selection == 'repo-map':
        import repo_map                                                      # noqa: E402  (only when asked: the default path never loads it)
        size = dict(rows); limit = cap * 4                                   # a file over this cannot be included: it is not read for its tags
        def read(path):
            if size[path] > limit: return None
            try: return reader.blob(sha, path)
            except Exception: return None
        scores, map_stats = repo_map.score_files([p for p, _ in rows if state[p] is None], read, mentions, repo_params, size)
    order = sorted((r for r in rows if state[r[0]] is None), key=lambda r: rank(r[0], priority, scores))
    kept = []; total = 0
    for path, nbytes in order:
        if total + nbytes > cap * 4: state[path] = 'not included (cap)'; continue   # a UTF-8 character is at most 4 bytes: cannot fit
        try: data = reader.blob(sha, path)
        except Exception as e: state[path] = f'not read ({getattr(e, "code", type(e).__name__)})'; continue
        if b'\0' in data[:8000]: state[path] = 'binary (NUL)'; continue
        try: text, how = data.decode('utf-8'), 'included'
        except UnicodeDecodeError: text, how = data.decode(FALLBACK_ENCODING, 'replace'), f'included (decoded as {FALLBACK_ENCODING})'
        if total + len(text) > cap: state[path] = 'not included (cap)'; continue
        total += len(text); kept.append((path, text)); state[path] = how
    out = [f'# Y = {name}@{sha}: whole-reading digest (no LLM): full tree then {len(kept)} whole text files, '
           f'{total} characters (cap {cap}); files not included are marked in the tree with the reason.'
           + (' Order within each tier: repository map (PageRank of the identifier graph).' if scores is not None else ''),
           f'# Expected citation: <path>:<line>@{sha}', '', f'## Tree ({len(rows)} files, bytes, state)']
    for path, nbytes in rows: out.append(f'{nbytes:>9}  {path}  [{state[path]}]')
    out += ['', '## Files (whole, numbered as git numbers them)', '']
    for path, text in kept:
        lines = git_lines(text)
        out.append(f'=== {path} @{sha} ({len(lines)} lines) ===')
        out += [f'{i}\t{l}' for i, l in enumerate(lines, 1)]; out.append('')
    text = '\n'.join(out) + '\n'
    summary = dict(repo=name, sha=sha, tree_files=len(rows), included=len(kept), chars_files=total, chars_total=len(text),
                   cap=cap, priority=list(priority), exclude=list(exclude),
                   reasons={r: sum(1 for v in state.values() if v == r) for r in sorted(set(state.values()))},
                   not_included_cap=[p for p, v in state.items() if v == 'not included (cap)'], selection=selection,
                   kept_paths=[p for p, _ in kept], repo_map=map_stats)
    return text, summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--repo', required=True); ap.add_argument('--sha', required=True); ap.add_argument('--name', required=True)
    ap.add_argument('--out', required=True); ap.add_argument('--cap', type=int, default=int(WR.get('y_cap_chars', 400000)))
    ap.add_argument('--priority', nargs='*', default=[]); ap.add_argument('--exclude', nargs='*', default=[])
    ap.add_argument('--selection', choices=SELECTIONS, default=None, help=f'order of the candidates under the cap (default: config condense.selection = {DEFAULT_SELECTION})')
    ap.add_argument('--run', help='run directory (scope.md, searches/*.md, capsule.md): identifiers and paths to personalise the repo-map on')
    a = ap.parse_args()
    rdr = LocalRepo(a.repo); ment = None
    if a.run and (a.selection or DEFAULT_SELECTION) == 'repo-map':
        import repo_map; ment = repo_map.mentions_from_run(a.run, rdr.resolve(a.sha))
    text, summary = condense(rdr, a.sha, a.name, a.cap, a.priority, a.exclude, a.selection, ment)
    pathlib.Path(a.out).write_text(text)
    print(json.dumps(summary, ensure_ascii=False, indent=1))

if __name__ == '__main__': main()
