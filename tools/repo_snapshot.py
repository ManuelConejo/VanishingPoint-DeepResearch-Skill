"""One commit of a public repository as a local bare snapshot, read by git without any API search (engine repo-grep, tools/sources/repo_grep.py).

Fetch: `git init --bare` (no template) in a bounded cache, then `git fetch --depth 1 --no-tags <origin> <SHA40>:refs/vp/snapshot` from
https://github.com/<owner>/<name> (github_repo.web): one commit, no history, no working tree, never a checkout. Read: `git grep` (fixed
string after -e, the pattern can start with '-'), `git ls-tree` and `git cat-file blob <sha>:<path>` on that commit. Nothing of the repository is ever executed:
  - no system or global configuration (GIT_CONFIG_NOSYSTEM, GIT_CONFIG_GLOBAL=/dev/null, an empty HOME of the cache), only the -c below;
  - core.hooksPath=/dev/null (no hook), core.fsmonitor=false, core.attributesFile=/dev/null, --no-textconv (no diff driver), no checkout
    (no smudge/clean filter, no LFS, no submodule: submodule.recurse=false, fetch.recurseSubmodules=false, GIT_LFS_SKIP_SMUDGE=1);
  - protocol.allow=never then protocol.https.allow=always (GIT_ALLOW_PROTOCOL=https too); file:// only through the explicit `file_origins`
    parameter of the tests (None by default: the origin is always built from github_repo.web, which must be https);
  - fetch.fsckObjects / transfer.fsckObjects (malformed objects refused), GIT_TERMINAL_PROMPT=0, credential.helper reset, no credential sent;
  - subprocesses as argument lists (never a shell), bounded by timeouts; the fetch is killed past repo_grep.max_fetch_bytes on disk;
  - cache entries removed only by shutil.rmtree on a path built here and checked to be a direct child of the cache root.
Every failure is typed: git_missing, fetch_failed, too_large, commit_missing, git_failed (the caller can fall back on the API tools).
Bounds and timeouts: config.json repo_grep."""
import json, os, pathlib, re, shutil, signal, subprocess, tempfile, threading, time
import code_sources as sc
try: import resource                                                      # POSIX only: the memory bound of git (absent on Windows)
except ImportError: resource = None

RG = sc.CFG['repo_grep']
SHA40 = re.compile(r'[0-9a-f]{40}')
ENTRY = re.compile(r'[A-Za-z0-9-]+_[A-Za-z0-9._-]+_[0-9a-f]{40}')        # <owner>_<name>_<sha40> (an owner never holds '_')
TMP = re.compile(r'tmp-[A-Za-z0-9_]+')                                    # a fetch in progress (tempfile.mkdtemp prefix)
MARK = 'vp-snapshot.json'                                                 # written inside an entry once its fetch is complete and checked
REF = 'refs/vp/snapshot'
READ = 'none'                                                             # protocol allowed to local reads: none exists (no network after the fetch)
PROXY_VARS = ('https_proxy', 'HTTPS_PROXY', 'no_proxy', 'NO_PROXY')        # passed through (network routing only, never code)


class SnapshotError(Exception):
    """A typed failure: code in git_missing, fetch_failed, too_large, commit_missing, git_failed; reason = a short plain text."""
    def __init__(self, code, reason):
        super().__init__(code); self.code, self.reason = code, reason


def _plain(b, n=None):
    """Bytes or text of git (stderr, a matched line) -> one plain line: control characters but tab folded to spaces, cut at n characters."""
    t = b.decode('utf-8', 'replace') if isinstance(b, bytes) else str(b)
    t = t.translate({c: ' ' for c in range(32) if c != 9}).replace('\x7f', ' ').strip()
    return t[:int(n if n is not None else RG['stderr_chars'])]


def _size(path):
    """Bytes of the regular files under path (symbolic links not followed)."""
    total = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        for f in files:
            try: total += os.lstat(os.path.join(root, f)).st_size
            except OSError: pass
    return total


def _bound(proc):
    """Address-space limit repo_grep.git_max_memory_bytes on a git process just started (Linux prlimit; Codex review 2026-10-31, item 6:
    a small, highly compressible blob inflates in memory). Set from outside after exec (no preexec_fn, unsafe with threads); git starts
    its work after that. Not available: nothing done (POSIX without prlimit, Windows)."""
    lim = int(RG.get('git_max_memory_bytes') or 0)
    if lim and resource is not None and hasattr(resource, 'prlimit'):
        try: resource.prlimit(proc.pid, resource.RLIMIT_AS, (lim, lim))
        except (OSError, ValueError): pass
    return proc


def _kill(proc):
    """Kills the process and its children (a fetch runs git-remote-https and index-pack); POSIX process group, else the process alone."""
    try:
        if hasattr(os, 'killpg'): os.killpg(proc.pid, signal.SIGKILL)
        else: proc.kill()
    except (OSError, ProcessLookupError): pass


class Snapshot:
    """Bounded cache of bare one-commit snapshots under `root` (created if absent). file_origins: tests only, {<owner>/<name>: local
    directory} fetched through file:// (protocol.file.allow); None (default) = https://github.com/<owner>/<name> only."""
    def __init__(self, root, file_origins=None):
        self.root = pathlib.Path(root).resolve()
        self.file_origins = file_origins
        self.git = shutil.which('git', path=os.environ.get('PATH', ''))   # absent or empty PATH -> None -> git_missing

    # ------------------------------------------------------------------ environment and command lines
    def _env(self, scheme):
        home = self.root / '.home'
        home.mkdir(parents=True, exist_ok=True)
        env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(home), 'XDG_CONFIG_HOME': str(home), 'LC_ALL': 'C',
               'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_ATTR_NOSYSTEM': '1', 'GIT_TERMINAL_PROMPT': '0',
               'GIT_ALLOW_PROTOCOL': scheme, 'GIT_PROTOCOL_FROM_USER': '0', 'GIT_LFS_SKIP_SMUDGE': '1', 'GIT_NO_REPLACE_OBJECTS': '1',
               'GIT_LITERAL_PATHSPECS': '1', 'GIT_OPTIONAL_LOCKS': '0', 'GIT_PAGER': 'cat', 'GIT_CEILING_DIRECTORIES': str(self.root)}
        env.update({k: os.environ[k] for k in PROXY_VARS if os.environ.get(k)})
        return env

    @staticmethod
    def _conf(scheme):
        """The only configuration git reads besides the snapshot's own (written by git init, no template)."""
        c = ['core.hooksPath=' + os.devnull, 'core.fsmonitor=false', 'core.attributesFile=' + os.devnull, 'credential.helper=',
             'protocol.allow=never', f'protocol.{scheme}.allow=always', 'protocol.version=2', 'submodule.recurse=false',
             'fetch.recurseSubmodules=false', 'fetch.fsckObjects=true', 'transfer.fsckObjects=true', 'gc.auto=0', 'maintenance.auto=false',
             'grep.fallbackToNoIndex=false', 'core.pager=cat']
        return [x for kv in c for x in ('-c', kv)]

    def _cmd(self, gitdir, scheme, *args):
        return [self.git, *self._conf(scheme), '--git-dir=' + str(gitdir), *args]

    def _run(self, argv, scheme, timeout):
        """A short git command (init, cat-file, rev-parse): -> (returncode, stdout bytes, stderr bytes); timeout -> git_failed."""
        try: p = _bound(subprocess.Popen(argv, env=self._env(scheme), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         cwd=str(self.root)))
        except OSError as e: raise SnapshotError('git_missing', f'git could not be started ({type(e).__name__})')
        try: out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill(); p.communicate()
            raise SnapshotError('git_failed', f'git timed out after {timeout} s (repo_grep.git_timeout_s)')
        return p.returncode, out, err

    # ------------------------------------------------------------------ cache
    def _entry(self, repo, sha):
        sc.GitHubRepo.check(repo)
        if not SHA40.fullmatch(sha or ''): raise SnapshotError('commit_missing', 'a 40-hex SHA is required to fetch a snapshot')
        name = repo.replace('/', '_', 1) + '_' + sha
        if not ENTRY.fullmatch(name): raise SnapshotError('fetch_failed', 'repository name not usable as a cache entry')
        return self._child(name)

    def _child(self, name):
        """root/<name>, checked: a direct child of the cache root, named like an entry or a fetch in progress, not a symbolic link."""
        p = self.root / name
        if not (ENTRY.fullmatch(name) or TMP.fullmatch(name)) or p.parent != self.root or p.is_symlink():
            raise ValueError('not a cache entry: ' + str(p))
        return p

    def _remove(self, path):
        """shutil.rmtree of a cache entry only (path rebuilt from its name and checked by _child); anything else is refused."""
        path = pathlib.Path(path)
        if path.parent.resolve() != self.root: raise ValueError('outside the cache root: ' + str(path))
        p = self._child(path.name)
        if p.exists(): shutil.rmtree(p)

    def entries(self):
        """Complete entries, most recently used first: [(path, used epoch, bytes)]."""
        out = []
        if not self.root.is_dir(): return out
        for p in self.root.iterdir():
            if not ENTRY.fullmatch(p.name) or p.is_symlink() or not (p / MARK).is_file(): continue
            try: m = json.loads((p / MARK).read_text()); out.append((p, (p / MARK).stat().st_mtime, int(m.get('bytes') or 0)))
            except (OSError, ValueError): continue
        return sorted(out, key=lambda x: -x[1])

    def evict(self, keep=None):
        """Least recently used entries removed beyond repo_grep.cache_max_entries or repo_grep.cache_max_bytes (the entry `keep` stays);
        incomplete entries and fetches left over for more than repo_grep.stale_tmp_s removed. -> names removed."""
        removed, now = [], time.time()
        if self.root.is_dir():
            for p in self.root.iterdir():
                stale = TMP.fullmatch(p.name) or (ENTRY.fullmatch(p.name) and not (p / MARK).is_file())
                try: old = now - p.stat().st_mtime > float(RG['stale_tmp_s'])
                except OSError: continue
                if stale and old and not p.is_symlink(): self._remove(p); removed.append(p.name)
        count = total = 0
        for p, _, b in self.entries():
            count += 1; total += b
            if keep is not None and p == keep: continue
            if count > int(RG['cache_max_entries']) or total > int(RG['cache_max_bytes']):
                self._remove(p); removed.append(p.name); count -= 1; total -= b
        return removed

    # ------------------------------------------------------------------ fetch
    def origin(self, repo):
        """(url, scheme) of the repository: https://github.com/<owner>/<name> (github_repo.web), or file:// through file_origins (tests)."""
        if self.file_origins is not None:
            if repo not in self.file_origins: raise SnapshotError('fetch_failed', 'no file origin given for this repository (tests only)')
            return pathlib.Path(self.file_origins[repo]).resolve().as_uri(), 'file'
        if not sc.GH['web'].startswith('https://'): raise SnapshotError('fetch_failed', 'github_repo.web is not an https URL: refused')
        return sc.GH['web'] + sc.GitHubRepo.check(repo), 'https'

    def _fetch(self, gitdir, url, scheme, sha):
        """git fetch --depth 1 of one commit, killed on timeout (repo_grep.fetch_timeout_s) or once the snapshot on disk exceeds
        repo_grep.max_fetch_bytes (checked every repo_grep.poll_s and at the end)."""
        argv = self._cmd(gitdir, scheme, 'fetch', '--quiet', '--depth=1', '--no-tags', '--no-recurse-submodules', '--no-write-fetch-head',
                         url, sha + ':' + REF)
        limit, deadline = int(RG['max_fetch_bytes']), time.monotonic() + float(RG['fetch_timeout_s'])
        with tempfile.TemporaryFile() as err:
            try: proc = _bound(subprocess.Popen(argv, env=self._env(scheme), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err,
                                                cwd=str(self.root), start_new_session=True))
            except OSError as e: raise SnapshotError('git_missing', f'git could not be started ({type(e).__name__})')
            code = None
            while proc.poll() is None:
                if _size(gitdir) > limit: _kill(proc); proc.wait(); code = 'too_large'; break
                if time.monotonic() > deadline: _kill(proc); proc.wait(); code = 'timeout'; break
                time.sleep(float(RG['poll_s']))
            err.seek(0); msg = _plain(err.read(int(RG['stderr_chars']) * 4))
        size = _size(gitdir)
        if code == 'too_large' or size > limit:
            raise SnapshotError('too_large', f'snapshot over repo_grep.max_fetch_bytes ({limit:,} bytes) on disk: fetch stopped')
        if code == 'timeout': raise SnapshotError('fetch_failed', f"fetch timed out after {RG['fetch_timeout_s']} s (repo_grep.fetch_timeout_s)")
        if proc.returncode != 0: raise SnapshotError('fetch_failed', f'git fetch exited {proc.returncode}: {msg}')
        return size

    def ensure(self, repo, sha):
        """The snapshot of <owner>/<name> at the 40-hex SHA: from the cache, else fetched. -> {'gitdir', 'bytes', 'seconds', 'cached'}."""
        if not self.git: raise SnapshotError('git_missing', 'git is not on PATH')
        final = self._entry(repo, sha)
        url, scheme = self.origin(repo)
        if (final / MARK).is_file():
            m = json.loads((final / MARK).read_text())
            rc, _, _ = self._run(self._cmd(final, READ, 'cat-file', '-e', sha + '^{commit}'), READ, float(RG['git_timeout_s']))
            if rc == 0:
                os.utime(final / MARK)
                return dict(gitdir=final, bytes=m.get('bytes'), seconds=m.get('seconds'), cached=True)
            self._remove(final)
        self.root.mkdir(parents=True, exist_ok=True)
        self.evict()
        tmp = self._child(pathlib.Path(tempfile.mkdtemp(prefix='tmp-', dir=str(self.root))).name)
        try:
            t0 = time.monotonic()
            rc, _, err = self._run([self.git, *self._conf(READ), 'init', '--quiet', '--bare', '--template=', str(tmp)], READ, float(RG['git_timeout_s']))
            if rc != 0: raise SnapshotError('git_failed', 'git init: ' + _plain(err))
            size = self._fetch(tmp, url, scheme, sha)
            rc, out, _ = self._run(self._cmd(tmp, READ, 'rev-parse', '--verify', '--quiet', REF + '^{commit}'), READ, float(RG['git_timeout_s']))
            if rc != 0 or out.decode('ascii', 'replace').strip() != sha:
                raise SnapshotError('commit_missing', 'the fetched reference is not the commit asked')
            secs = round(time.monotonic() - t0, 2)
            (tmp / MARK).write_text(json.dumps({'repo': repo, 'sha': sha, 'origin': url, 'bytes': size, 'seconds': secs,
                                                'fetched_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}))
            try: os.rename(tmp, final)
            except OSError:                                                # another process stored the same entry meanwhile
                self._remove(tmp)
                if not (final / MARK).is_file(): raise SnapshotError('fetch_failed', 'cache entry could not be stored')
        except BaseException:
            if tmp.exists(): self._remove(tmp)
            raise
        self.evict(keep=final)
        return dict(gitdir=final, bytes=size, seconds=secs, cached=False)

    # ------------------------------------------------------------------ reads
    def _stream(self, argv, scheme, timeout, max_records, sep):
        """Records of a long git command (grep, ls-tree) read as they come: at most max_records (then the process is killed: truncated),
        killed after `timeout` seconds. Bytes bounded too (Codex review 2026-10-31, item 6): one record is kept up to repo_grep.record_max_bytes
        (the rest of it is read and dropped, never held), and the process is killed (truncated) once the records kept would pass
        repo_grep.output_max_bytes. -> (records, truncated, returncode, stderr)."""
        recs, truncated, kept = [], False, 0
        rmax, omax = int(RG['record_max_bytes']), int(RG['output_max_bytes'])
        with tempfile.TemporaryFile() as err:
            try: proc = _bound(subprocess.Popen(argv, env=self._env(scheme), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err,
                                                cwd=str(self.root), start_new_session=True))
            except OSError as e: raise SnapshotError('git_missing', f'git could not be started ({type(e).__name__})')
            fired = []
            timer = threading.Timer(timeout, lambda: (fired.append(1), _kill(proc))); timer.start()

            def keep(rs):
                nonlocal kept, truncated
                for r in rs:
                    r = r[:rmax]
                    if len(recs) >= max_records + 1 or kept + len(r) > omax: truncated = True; return False
                    recs.append(r); kept += len(r)
                return True
            try:
                buf, head = b'', None                                    # head: kept prefix of a record longer than record_max_bytes, end not read yet
                while True:
                    chunk = proc.stdout.read1(65536) if hasattr(proc.stdout, 'read1') else proc.stdout.read(65536)
                    if not chunk: break
                    buf += chunk
                    *done, buf = buf.split(sep)
                    if done and head is not None: done[0], head = head, None
                    if head is not None: buf = b''                       # still inside the long record: dropped as it comes
                    elif len(buf) > rmax: head, buf = buf[:rmax], b''
                    if not keep(done) or len(recs) > max_records: truncated = True; _kill(proc); break
                if not truncated and (buf or head is not None): keep([head if head is not None else buf])
                proc.wait()
            finally:
                timer.cancel()
                proc.stdout.close()
            timed_out = bool(fired) and not truncated
            err.seek(0); msg = _plain(err.read(int(RG['stderr_chars']) * 4))
        if timed_out: raise SnapshotError('git_failed', f'git stopped after {timeout} s (repo_grep.grep_timeout_s)')
        return recs[:max_records], truncated, proc.returncode, msg

    def grep(self, snap, sha, pattern, paths=(), ignore_case=False):
        """git grep of a fixed string at the commit -> {'matches': [{'path', 'line', 'text'}], 'truncated', 'skipped_paths'}; at most
        repo_grep.max_matches lines scanned (then truncated), each text cut at repo_grep.line_chars."""
        argv = self._cmd(snap['gitdir'], READ, 'grep', '-n', '-z', '-I', '--no-textconv', '--no-color', '-F',
                         *(['-i'] if ignore_case else []), '-e', pattern, sha, '--', *paths)
        recs, truncated, rc, msg = self._stream(argv, READ, float(RG['grep_timeout_s']), int(RG['max_matches']), b'\n')
        if rc not in (0, 1) and not truncated: raise SnapshotError('git_failed', f'git grep exited {rc}: {msg}')
        out, skipped, head = [], 0, (sha + ':').encode()
        for r in recs:
            parts = r.split(b'\0', 2)
            if len(parts) != 3 or not parts[0].startswith(head) or not parts[1].isdigit(): skipped += 1; continue
            path = parts[0][len(head):].decode('utf-8', 'replace')
            if not sc.path_ok(path): skipped += 1; continue
            out.append({'path': path, 'line': int(parts[1]), 'text': _plain(parts[2], RG['line_chars'])})
        return {'matches': out, 'truncated': truncated, 'skipped_paths': skipped}

    def show(self, snap, sha, path, max_bytes):
        """One file of the commit as bytes: `git cat-file blob <sha>:<path>` (no textconv, no filter, nothing executed), refused beyond
        max_bytes (the size is asked first with `cat-file -s`). -> bytes; absent -> SnapshotError('git_failed')."""
        if not sc.path_ok(path): raise SnapshotError('git_failed', 'not a repository-relative path')
        obj = sha + ':' + path
        rc, out, err = self._run(self._cmd(snap['gitdir'], READ, 'cat-file', '-s', obj), READ, float(RG['git_timeout_s']))
        if rc != 0: raise SnapshotError('git_failed', 'path absent at the commit: ' + _plain(err))
        size = int(out.decode('ascii', 'replace').strip() or 0)
        if size > int(max_bytes): raise SnapshotError('too_large', f'file of {size:,} bytes over the bound of {int(max_bytes):,} bytes')
        rc, out, err = self._run(self._cmd(snap['gitdir'], READ, 'cat-file', 'blob', obj), READ, float(RG['git_timeout_s']))
        if rc != 0: raise SnapshotError('git_failed', 'git cat-file: ' + _plain(err))
        return out

    def ls(self, snap, sha, paths=()):
        """git ls-tree -r -l of the commit -> {'files': [{'path', 'bytes'}], 'submodules': [paths], 'truncated'}; at most
        repo_grep.ls_paths_scanned entries read."""
        argv = self._cmd(snap['gitdir'], READ, 'ls-tree', '-r', '-l', '-z', '--full-tree', sha, '--', *paths)
        recs, truncated, rc, msg = self._stream(argv, READ, float(RG['grep_timeout_s']), int(RG['ls_paths_scanned']), b'\0')
        if rc != 0 and not truncated: raise SnapshotError('git_failed', f'git ls-tree exited {rc}: {msg}')
        files, subs = [], []
        for r in recs:
            meta, _, path = r.partition(b'\t')
            f = meta.split()
            path = path.decode('utf-8', 'replace')
            if len(f) != 4 or not sc.path_ok(path): continue
            if f[1] == b'blob': files.append({'path': path, 'bytes': int(f[3]) if f[3].isdigit() else None})
            elif f[1] == b'commit': subs.append(path)                       # a submodule: listed, never followed
        return {'files': files, 'submodules': subs, 'truncated': truncated}
