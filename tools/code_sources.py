# SPDX-License-Identifier: Apache-2.0
"""Code sources of the VanishingPoint gateway. CodeClient = HTTPS only, closed host list, no redirect, 5 MB cap, per-host
interval from config.json, receipts without URL nor token; grep.app disabled; every key optional (GitHub token: VP_GITHUB_TOKEN
resolved by key('VP_GITHUB_TOKEN'), sent to api.github.com only, never logged; SWH_TOKEN sent to archive.softwareheritage.org only);
VP_OFFLINE=1 = no network. A key the provider rejects is remembered in <state>/keys-invalid.json (names only) and not sent again.
key(NAME) is the single key rule of the skill (KEYS.md), also used by gateway.py."""
import datetime
import fcntl
import hashlib
import html
import io
import json
import os
import pathlib
import re
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode, urlsplit

CFG = json.loads((pathlib.Path(__file__).resolve().parent / 'config.json').read_text())
INTERVAL = CFG['code_intervals']
HL = CFG['http_limits']                            # deadlines, byte caps, cache and receipt sizes of the HTTP clients (Codex review 2026-10-31, items 9-10)
GH = CFG['github_repo']                            # engine github-repo: API, raw and web bases (config.json github_repo)
GH_API_HOST, GH_RAW_HOST = urlsplit(GH['api']).hostname, urlsplit(GH['raw']).hostname
RM = CFG['repo_metadata']                          # keyless repository metadata: ecosyste.ms repos, deps.dev projects, OSV by commit
HOSTS = frozenset(('api.github.com', 'sourcegraph.com', 'api.deps.dev', 'pypi.org', 'registry.npmjs.org', 'crates.io',
                   'huggingface.co', 'archive.softwareheritage.org', 'api.osv.dev', GH_API_HOST, GH_RAW_HOST))
CRED_HOST = {'VP_GITHUB_TOKEN': 'api.github.com', 'SWH_TOKEN': 'archive.softwareheritage.org'}   # each credential goes to its own host only
TOKEN_PATH = None     # no token file fallback (kept as a module variable so tests can monkeypatch it harmlessly)
FALLBACK_DIRS = ()    # no fallback key directory (kept as a module variable so tests can monkeypatch it harmlessly)
MAX_BYTES, MAX_QUERY = 5_000_000, 512
UA = 'VanishingPoint/1 (research skill)'   # replaced below once key() is defined: VP_CONTACT follows the key rule (env, then ~/.config/vp/vp_contact.key)
SWH = 'https://archive.softwareheritage.org/'
ORIGIN = r'https://[A-Za-z0-9.-]+(?::\d+)?/\S*'   # an origin for Software Heritage: HTTPS, a plain host (no userinfo), a path
SWHID = r'swh:1:(cnt|dir|rev|rel|snp):[a-f0-9]{40}'
CODE_FILE = r'(https://[A-Za-z0-9.-]+(?::\d+)?/[^\s#]*)#([^\s@#]+)@([a-f0-9]{40})'   # code-file <origin>#<path>@<40-hex SHA> (verifier)


def _reset_epoch(headers):
    """Epoch seconds when a rate limit ends: X-RateLimit-Reset (epoch, GitHub), else now + Retry-After (seconds); None when neither is a number."""
    try: return int(str(headers.get('X-RateLimit-Reset')).strip())
    except (TypeError, ValueError): pass
    try: return int(time.time()) + int(str(headers.get('Retry-After')).strip())
    except (TypeError, ValueError): return None


def _header(headers, name):
    """Header value, case-insensitive (http.client.HTTPMessage or a plain dict in tests); '' when absent."""
    try: v = headers.get(name)
    except AttributeError: v = None
    if v is None and isinstance(headers, dict): v = next((x for k, x in headers.items() if str(k).lower() == name.lower()), None)
    return str(v or '').strip()


def read_bounded(resp, max_bytes, deadline):
    """Body of an HTTP response read in chunks of what is available (read1: a server sending one byte at a time cannot fill a fixed-size
    read), at most max_bytes + 1 bytes (the caller sees the excess), TimeoutError once the monotonic deadline has passed."""
    out, n = [], 0
    rd = getattr(resp, 'read1', None) or resp.read
    while n <= max_bytes:
        if time.monotonic() > deadline: raise TimeoutError('deadline')
        b = rd(min(65536, max_bytes + 1 - n))
        if not b: break
        out.append(b); n += len(b)
    return b''.join(out)


def with_deadline(fn, seconds):
    """fn() in a worker thread joined with an absolute deadline (headers included, which read_bounded cannot bound): its result, its own
    exception, or TimeoutError when it is still running (the daemon thread ends with its socket timeout; nothing of it is used)."""
    box = {}

    def run():
        try: box['v'] = fn()
        except BaseException as e: box['e'] = e                         # noqa: B902 (re-raised in the caller's thread)
    t = threading.Thread(target=run, daemon=True); t.start(); t.join(seconds)
    if t.is_alive(): raise TimeoutError('deadline')
    if 'e' in box: raise box['e']
    return box['v']


_CACHE_USE = {}   # cache dir -> bytes it holds (summed once per process, then counted at each write)


def cache_room(d, n):
    """True (and counted) when n more bytes fit in the HTTP cache dir d under http_limits.cache_max_bytes; False = serve, do not cache.
    Nothing is evicted: the cache is evidence of the run (evidence_bank, finish_run)."""
    k = str(d)
    if k not in _CACHE_USE:
        try: _CACHE_USE[k] = sum(e.stat(follow_symlinks=False).st_size for e in os.scandir(d) if e.is_file(follow_symlinks=False))
        except OSError: _CACHE_USE[k] = 0
    if _CACHE_USE[k] + n > int(HL['cache_max_bytes']): return False
    _CACHE_USE[k] += n
    return True


def append_receipt(path, line):
    """Appends one receipt line to <state>/requests.jsonl, rotated to requests.jsonl.1 beyond http_limits.receipts_max_bytes."""
    path = pathlib.Path(path)
    try:
        if path.stat().st_size > int(HL['receipts_max_bytes']): os.replace(path, path.with_name(path.name + '.1'))
    except OSError: pass
    with open(path, 'a') as f:
        f.write(line + '\n')


def refuse(condition, code):
    """Typed refusal: every adapter error is a short ValueError code, never a message built from data."""
    if condition:
        raise ValueError(code)


class RedirectRefused(ValueError):
    """A redirection, never followed by the transport; `location` is kept for the caller (GitHubRepo follows api.github.com -> api.github.com only)."""
    def __init__(self, location):
        super().__init__('redirect_refused'); self.location = location


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # refused before any second request
        raise RedirectRefused(newurl)


class CodeClient:
    def __init__(self, hosts=HOSTS, interval=None, cache_dir=None, offline=False):
        self.hosts, self.interval = frozenset(hosts), dict(INTERVAL, **(interval or {}))
        self.cache_dir = pathlib.Path(cache_dir) if cache_dir else None  # receipts, cache and last-call files
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = bool(offline) or os.environ.get('VP_OFFLINE') == '1'
        self.last, self.waited, self.receipts = {}, [], []
        self.rate_reset = {}  # host -> epoch seconds announced with a rate-limited answer (X-RateLimit-Reset, else now + Retry-After)
        self.clock, self.sleep = time.monotonic, time.sleep  # tests replace them; waited records every wait anyway
        self.opener = urllib.request.build_opener(_NoRedirect())
        self.redirects = {}   # url -> location of a refused redirection to the same host over https (read by GitHubRepo._api), never followed here

    def _wait(self, host, keyed=False):
        """Minimum interval per host: monotonic in-process, and shared with the other processes of the same state dir (locked file);
        '<host>+token' in config.json code_intervals = the interval when a credential is sent (Software Heritage token)."""
        iv = self.interval[host + '+token'] if keyed and host + '+token' in self.interval else self.interval.get(host, self.interval['default'])
        with open(self.cache_dir / f'rate-code-{host}', 'a+') if self.cache_dir else io.StringIO() as f:
            if self.cache_dir:
                fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            wait = max(self.last.get(host, -iv) + iv - self.clock(), float(f.read().strip() or 0) + iv - time.time())
            if wait > 0:
                self.waited.append((host, round(wait, 3)))
                self.sleep(wait)
            self.last[host] = self.clock()
            f.seek(0)
            f.truncate()
            f.write(str(time.time()))

    def _send(self, url, headers, body=None):
        """One request under http_limits: socket_timeout_s per socket operation, total_timeout_s for the whole call (headers and body),
        at most MAX_BYTES + 1 bytes read."""
        total = float(HL['total_timeout_s']); deadline = time.monotonic() + total

        def go():
            with self.opener.open(urllib.request.Request(url, data=body, headers=headers), timeout=float(HL['socket_timeout_s'])) as r:
                return r.status, read_bounded(r, MAX_BYTES, deadline)
        return with_deadline(go, total)

    def _record(self, rec):
        self.receipts.append(rec)
        if self.cache_dir:
            append_receipt(self.cache_dir / 'requests.jsonl', json.dumps(rec))

    def get(self, url, token=None, cred='VP_GITHUB_TOKEN', body=None):
        """GET (POST JSON when body is given, e.g. OSV); token = value of the credential `cred`, sent to CRED_HOST[cred] only."""
        u = urlsplit(url)
        refuse(u.scheme != 'https' or u.port not in (None, 443) or u.username or u.password or u.hostname not in self.hosts, 'host_not_declared')
        refuse(token and u.hostname != CRED_HOST.get(cred), 'credential_host')
        raw = self.cache_dir / 'cache' / hashlib.sha256(url.encode() + (b'\0' + body if body else b'')).hexdigest() if self.cache_dir else None
        if raw and raw.exists():
            return raw.read_bytes()
        if self.offline:
            raise RuntimeError('offline')
        headers = {'Accept': 'application/json, text/event-stream', 'User-Agent': UA, **({'Authorization': 'Bearer ' + token} if token else {}),
                   **({'Content-Type': 'application/json'} if body else {})}
        self._wait(u.hostname, keyed=bool(token))
        t0 = time.time()
        rec = {'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t0)), 'host': u.hostname,
               'path_sha256': hashlib.sha256((u.path + '?' + u.query).encode()).hexdigest(), 'status': None, 'bytes': 0, 'sha256': None, 'seconds': 0.0}
        code = None
        try:
            status, data = self._send(url, headers) if body is None else self._send(url, headers, body)
        except urllib.error.HTTPError as e:
            hd = getattr(e, 'headers', None) or {}                      # GitHub signals an exhausted quota by 403 + X-RateLimit-Remaining: 0 (or Retry-After)
            limited = e.code == 403 and (str(hd.get('X-RateLimit-Remaining') or '') == '0' or bool(hd.get('Retry-After')))
            code = 'rate_limited' if e.code in (429, 503) or limited else f'provider_error:HTTP{e.code}'
            if _header(hd, 'cf-mitigated').lower() == 'challenge': code = 'bot_challenge'   # Cloudflare anti-bot page: a technical block, never circumvented
            if code == 'rate_limited': self.rate_reset[u.hostname] = _reset_epoch(hd)
            self._record(dict(rec, status=e.code, seconds=round(time.time() - t0, 3)))
        except Exception as e:  # only our own 'redirect_refused' keeps its text; anything else is typed by name (no header, no URL, no token)
            code = 'redirect_refused' if str(e) == 'redirect_refused' else 'transport_error:' + type(e).__name__
            loc = urlsplit(str(getattr(e, 'location', '') or ''))
            if code == 'redirect_refused' and loc.scheme == 'https' and loc.hostname == u.hostname and loc.port in (None, 443) and not (loc.username or loc.password):
                self.redirects[url] = loc.geturl()                      # same host, https: the caller may decide to follow it
            self._record(dict(rec, failure=code, seconds=round(time.time() - t0, 3)))
        if code:
            raise ValueError(code)  # raised outside the except block: no __context__ that could carry a header value
        rec['seconds'] = round(time.time() - t0, 3)
        if len(data) > MAX_BYTES:  # the receipt is written for this call too
            self._record(dict(rec, status=status, bytes=len(data), failure='response_too_large'))
            raise ValueError('response_too_large')
        keep = bool(raw) and cache_room(raw.parent, len(data))
        self._record(dict(rec, status=status, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), **({'cache': 'full'} if raw and not keep else {})))
        if keep:
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(data)
        return data

    def json(self, url, token=None, **kw):
        try:
            return json.loads(self.get(url, token, **kw))
        except (json.JSONDecodeError, UnicodeError):
            raise ValueError('malformed_or_bot_challenge') from None


def check_query(q, regex=False, language=None, repo=None, path=None):
    refuse(not isinstance(q, str) or not q.strip() or len(q) > MAX_QUERY or any(ord(c) < 32 for c in q), 'query_invalid')
    refuse(regex and (any(c in q for c in '()|{}') or re.search(r'\\[1-9]|\(\?', q)), 'regex_unbounded')  # bounded subset only
    refuse(any(x and not re.fullmatch(r'[A-Za-z0-9_.+/#-]{1,160}', x) for x in (language, repo, path)), 'filter_invalid')


QUERY_FILTER = re.compile(r'(?:(?<=\s)|^)(repo|r|lang|language|file|path|f):(\S+)(?=\s|$)', re.I)   # filters typed inside a search-code pattern
QUERY_FILTER_KEY = {'repo': 'repo', 'r': 'repo', 'lang': 'language', 'language': 'language', 'file': 'path', 'path': 'path', 'f': 'path'}


def _typed_repo(v):
    """repo: value typed in a query -> <owner>/<name>, or a bare name fragment; the Sourcegraph regex spelling (^github\\.com/o/n$) and a
    github.com URL are reduced to it. Anything else -> ValueError('filter_invalid')."""
    v = re.sub(r'^\^|\$$', '', v).replace('\\.', '.')
    v = re.sub(r'^(?:https?://)?(?:www\.)?github\.com/', '', v).rstrip('/').removesuffix('.git')
    refuse(not (re.fullmatch(GH_REPO, v) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,100}', v)) or v.split('/')[-1] in ('.', '..'), 'filter_invalid')
    return v


def split_filters(q):
    """search-code: the filters typed inside the query (repo: / r:, lang: / language:, file: / path: / f:, whitespace-delimited tokens)
    -> (pattern without them, {'repo', 'language', 'path'}). A filter typed twice with two values -> ValueError('filter_conflict'); a value
    outside the filter alphabet -> ValueError('filter_invalid'). They become filters of the providers (Sourcegraph repo:/lang:/file:, GitHub
    repo:/language:/path:), never words of the literal pattern (internal code bench 2026-10-31: 14/22 calls at 0 result with repo: inside the pattern)."""
    found = {}
    for m in QUERY_FILTER.finditer(q if isinstance(q, str) else ''):
        k, v = QUERY_FILTER_KEY[m.group(1).lower()], m.group(2)
        v = _typed_repo(v) if k == 'repo' else v
        refuse(not re.fullmatch(r'[A-Za-z0-9_.+/#-]{1,160}', v), 'filter_invalid')
        refuse(k in found and found[k] != v, 'filter_conflict')
        found[k] = v
    return ' '.join(QUERY_FILTER.sub(' ', q).split()) if isinstance(q, str) else q, found


def hit(repo, path, line, revision, snippet, url=None):
    sha = revision if re.fullmatch(r'[0-9a-f]{40}', revision or '') else None
    permanent = f'https://github.com/{repo}/blob/{sha}/{quote(path, safe="/")}#L{line}' if sha and line else None
    return dict(repo=repo, path=path, line=line, revision=sha, snippet=snippet[:400], permanent_url=permanent, url=url or permanent)


def parse_sourcegraph(sse, limit=None):
    """Hits of a Sourcegraph stream; paths longer than implementations.path_max_chars skipped, at most `limit` hits built (Codex review
    2026-10-31, item 5: each hit holds a URL with the path, so the bounds apply before construction)."""
    out, cap = [], int(IMPL['path_max_chars'])
    for block in (b for b in sse.split('\n\n') if b.startswith('event: matches')):
        for h in json.loads('\n'.join(x[6:] for x in block.splitlines() if x.startswith('data: '))):
            if h.get('type') == 'content' and len(str(h.get('path') or '')) <= cap:
                for m in h.get('lineMatches', []):
                    if limit is not None and len(out) >= limit: return out
                    out.append(hit(h['repository'].removeprefix('github.com/'), h['path'], m['lineNumber'] + 1, h.get('commit'), m['line']))
    return out


def key(name):
    """Optional API key NAME, single rule (KEYS.md): 1. environment variable NAME; 2. ~/.config/vp/<name in lower case>.key
    (exact name, '_key' kept: OPENALEX_KEY -> openalex_key.key). No other fallback. Empty or unreadable = absent.
    None when absent; the value is never printed nor logged."""
    v = os.environ.get(name)
    if v and v.strip():
        return v.strip()
    try:
        v = (pathlib.Path.home() / '.config' / 'vp' / (name.lower() + '.key')).read_text().strip()
    except OSError:
        return None
    return v or None


def contact():
    """Identification contact VP_CONTACT, same rule as the keys (env, then ~/.config/vp/vp_contact.key); '' when absent."""
    return key('VP_CONTACT') or ''


UA = 'VanishingPoint/1 (+' + contact() + ')' if contact() else UA


def read_token():
    """Optional GitHub token: key('VP_GITHUB_TOKEN') only; None when absent; refused (never sent) unless printable ASCII."""
    token = key('VP_GITHUB_TOKEN')
    refuse(token is not None and not re.fullmatch(r'[\x21-\x7e]{8,}', token), 'credential_invalid')
    return token


INVALID_FILE = 'keys-invalid.json'   # names of the keys a provider rejected during the run (in the state dir); never a value


def invalid_keys(state):
    """Names of the keys rejected by their provider in this state dir (empty without a state dir or file)."""
    try: return set(json.loads((pathlib.Path(state) / INVALID_FILE).read_text())) if state else set()
    except (OSError, ValueError, TypeError): return set()


def mark_invalid(state, name):
    """Remembers that the provider rejected key NAME: the rest of the run goes on without it (flag `key_invalid`, name only)."""
    if not state: return
    d = pathlib.Path(state); d.mkdir(parents=True, exist_ok=True)
    with open(d / INVALID_FILE, 'a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX); f.seek(0)
        try: names = set(json.loads(f.read() or '[]'))
        except ValueError: names = set()
        f.seek(0); f.truncate(); f.write(json.dumps(sorted(names | {name})))


def swh_token(state=None):
    """Optional Software Heritage token: key('SWH_TOKEN'); None when absent, already rejected in this state dir, or not printable
    ASCII of at least 8 characters (then remembered as invalid, never sent)."""
    t = key('SWH_TOKEN')
    if t is None or 'SWH_TOKEN' in invalid_keys(state): return None
    if not re.fullmatch(r'[\x21-\x7e]{8,}', t): mark_invalid(state, 'SWH_TOKEN'); return None
    return t


GITHUB_CODE_SEARCH_KEYLESS = ('GitHub REST code search is unusable without a token: GET /search/code answers 401 "Requires authentication" '
                              '(probe 2026-10-31); no keyless GitHub code search exists (KEYS.md, VP_GITHUB_TOKEN)')
SG_LIMITS = CFG['sourcegraph_limits']   # bounded backoff and stop of the keyless Sourcegraph search (config.json sourcegraph_limits)
SG_STOP_FILE = 'sourcegraph-stopped.json'   # in the state dir: {'until', 'until_utc', 'code'} of a Sourcegraph stop (rate limit or challenge)


class CodeSearch:
    def __init__(self, client): self.c = client

    def sourcegraph_stopped(self):
        """(until epoch, code) of a Sourcegraph stop still running (this client, or <state>/SG_STOP_FILE), else None."""
        st = getattr(self.c, 'sourcegraph_stop', None)
        if st is None and self.c.cache_dir:
            try: d = json.loads((self.c.cache_dir / SG_STOP_FILE).read_text()); st = (float(d['until']), str(d['code']))
            except (OSError, ValueError, TypeError, KeyError): st = None
        return st if st and st[0] > time.time() else None

    def _sg_stop(self, code, seconds):
        until = int(time.time() + seconds)
        self.c.sourcegraph_stop = (until, code)
        if self.c.cache_dir:
            (self.c.cache_dir / SG_STOP_FILE).write_text(json.dumps({'until': until, 'until_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(until)), 'code': code}))

    def _sourcegraph_get(self, url):
        """One Sourcegraph request under the stop and the bounded backoff (config.json sourcegraph_limits): a stop still running -> no
        request, ValueError(<code of the stop>); 429 without challenge -> waits of retry_waits_s (Retry-After when announced and not longer
        than the longest of them), then a stop until the announced reset or stop_s; a Cloudflare challenge (cf-mitigated) -> no retry, stop
        challenge_stop_s (ACCESS-POLICY.md: a technical block is never circumvented)."""
        waits = [float(x) for x in SG_LIMITS['retry_waits_s']]
        for i in range(len(waits) + 1):
            if self.sourcegraph_stopped(): refuse(True, self.sourcegraph_stopped()[1])
            try: return self.c.get(url)
            except ValueError as e:
                if str(e) == 'bot_challenge': self._sg_stop('bot_challenge', float(SG_LIMITS['challenge_stop_s'])); raise
                if str(e) != 'rate_limited': raise
                reset = self.c.rate_reset.pop('sourcegraph.com', None)
                if i == len(waits):
                    self._sg_stop('rate_limited', max(float(SG_LIMITS['stop_s']), (reset or 0) - time.time())); raise
                ra = (reset - time.time()) if reset else None
                w = ra if ra is not None and 0 < ra <= max(waits) else waits[i]
                self.c.waited.append(('sourcegraph.com', round(w, 3))); self.c.sleep(w)

    def search(self, q, provider='sourcegraph', regex=False, language=None, repo=None, limit=10, path=None):
        check_query(q, regex, language, repo, path)
        refuse(not 1 <= limit <= 100, 'limit')
        refuse(provider == 'grep', 'provider_disabled')  # grep.app: 429 and anti-bot, live index, abandoned
        refuse(provider not in ('sourcegraph', 'github'), 'provider')
        full = bool(repo and re.fullmatch(GH_REPO, repo))                    # <owner>/<name> exact, else a name fragment
        if provider == 'sourcegraph':
            quoted = 'content:"' + q.replace('\\', '\\\\').replace('"', '\\"') + '"'   # q is the literal pattern (split_filters took the typed filters out)
            query = ('patterntype:regexp ' if regex else 'patterntype:literal ') + quoted + f' count:{limit} timeout:10s'
            query += (' lang:' + language if language else '') + (' file:' + re.escape(path) if path else '')
            query += (' repo:^github\\.com/' + re.escape(repo) + '$' if full else ' repo:' + re.escape(repo) if repo else '')
            s = self._sourcegraph_get('https://sourcegraph.com/.api/search/stream?' + urlencode({'q': query, 'v': 'V3'})).decode()
            refuse('event: error' in s or 'event: done' not in s, 'sourcegraph_incomplete')
            return parse_sourcegraph(s, limit)
        refuse(regex, 'github_rest_regex_unsupported')
        token = read_token()
        if not token:
            return {'status': 'skipped', 'reason': 'credential_missing', 'note': GITHUB_CODE_SEARCH_KEYLESS}
        if repo and not full: return {'status': 'skipped', 'reason': 'repo_fragment_unsupported (GitHub repo: needs <owner>/<name>)'}
        query = '"' + q.replace('"', '\\"') + '"' + (' language:' + language if language else '') + (' repo:' + repo if repo else '') + (' path:' + path if path else '')
        d = self.c.json('https://api.github.com/search/code?' + urlencode({'q': query, 'per_page': limit}), token)
        # h['sha'] is a blob hash, never a revision: no permanent URL until a commit is resolved
        return [hit(h['repository']['full_name'], h['path'], None, None, '', url=h['html_url']) for h in d['items']]


def check_ref(package, version):
    """Package (optionally npm-scoped: @scope/name) and version as URL segments: bounded alphabet, never '.', '..' or empty."""
    refuse(not re.fullmatch(r'@?[A-Za-z0-9][\w.+-]{0,200}(/[A-Za-z0-9][\w.+-]{0,200})?', package) or not re.fullmatch(r'[A-Za-z0-9][\w.+-]{0,100}', version)
           or any(s in ('.', '..') for s in package.split('/')) or version in ('.', '..'), 'reference')
    return quote(package, safe=''), quote(version, safe='')


class Versions:
    def __init__(self, client): self.c = client

    def metadata(self, system, package, version):
        p, v = check_ref(package, version)
        x = dict(package=package, version=version, date=None, dependencies=None, docs_candidates={}, version_doc_url=None, signature=None)
        if system == 'pypi':
            d = self.c.json(f'https://pypi.org/pypi/{p}/{v}/json')
            got = d['info']['version']
            x.update(dependencies=d['info'].get('requires_dist'), docs_candidates=d['info'].get('project_urls') or {},
                     date=min((u['upload_time_iso_8601'] for u in d.get('urls', []) if 'upload_time_iso_8601' in u), default=None))
        elif system == 'npm':
            d = self.c.json(f'https://registry.npmjs.org/{p}/{v}')
            got = d['version']
            x.update(dependencies=d.get('dependencies', {}), docs_candidates={'homepage': d.get('homepage')},
                     date=self.c.json(f'https://registry.npmjs.org/{p}').get('time', {}).get(version))
        else:
            refuse(system != 'cargo', 'system')
            d = self.c.json(f'https://crates.io/api/v1/crates/{p}/{v}')['version']
            got = d['num']
            x.update(date=d.get('created_at'), version_doc_url=f'https://docs.rs/{p}/{v}/',
                     dependencies=self.c.json(f'https://crates.io/api/v1/crates/{p}/{v}/dependencies').get('dependencies'))
        refuse(got != version, 'version_mismatch')
        return x

    def deps(self, system, package, version):
        refuse(system not in ('pypi', 'npm', 'cargo'), 'system')
        p, v = check_ref(package, version)
        root = f'https://api.deps.dev/v3/systems/{system.upper()}/packages/{p}/versions/{v}'
        d, graph = self.c.json(root), self.c.json(root + ':dependencies')
        return dict(package=package, version=version, date=d.get('publishedAt'), dependencies=graph.get('nodes'), edges=graph.get('edges'),
                    advisories=d.get('advisoryKeys', []), metadata=d)

    def documentation(self, package, version, symbol, url):
        """Textual call syntax at an exact versioned documentation URL (host to declare in CodeClient); never evaluated."""
        text, parts = ' '.join(re.sub('<[^>]+>', ' ', self.c.get(url).decode('utf-8', 'replace')).split()), urlsplit(url).path.split('/')
        pinned = version in parts and not any(x in parts for x in ('latest', 'stable'))
        found = re.search(r'(?<![\w.])' + re.escape(symbol) + r'\s*(\([^)]{0,2000}\))', text) if pinned else None
        return dict(symbol=symbol, version=version, version_doc_url=url if pinned else None, signature=found[1] if found else None,
                    status='found' if found else 'unknown')


class PaperCode:
    """paper-code <arXiv id>: what Hugging Face Papers links to a paper (audit 2026-10-31, items 4a-4d). The paper is dated by the earliest
    safe bound: its arXiv identifier (YYMM: submitted by the end of that month) and HF publishedAt (the HF date can be later: both kept,
    the gap marked). The declared githubRepo is dated on GitHub like repo-head (repository created before T, last commit of the default
    branch before T: its SHA is served), never by the paper's date; its stars are current (as_of now); an empty githubRepo is said, not read
    as "no code". Models, datasets and spaces are dated by their CREATION (Hub createdAt; the 2022-03-02 migration day attested by a commit
    before T), like search-hf-models, never by lastModified; licence and tags are served only when unchanged since before T."""
    def __init__(self, client, extra=None):
        self.c = client
        self.extra = extra if extra is not None else {}

    def _repo(self, url, stars, B):
        """The githubRepo entry: dated by the last commit of the default branch before T (GitHubRepo.head_gated) when B is given and config
        paper_code.date_github_repo; refused when the repository was created on/after T or holds no commit before T."""
        x = dict(url=meta(url), status='official_declared_hf', stars=stars, stars_as_of='now (not as of T)', date=None)
        repo = github_repo_of(str(url or '').strip().rstrip('/').removesuffix('.git'))
        if not repo: x['dating'] = 'absent (not a GitHub repository URL)'; return x
        x['repo'] = repo
        if B is None or not CFG['paper_code'].get('date_github_repo'):
            x['dating'] = 'absent (the link and the repository are current values of Hugging Face, not dated: check them with repo-head)'; return x
        try: h, why = GitHubRepo(self.c, self.extra).head_gated(repo, B, self.extra)
        except (ValueError, RuntimeError, AttributeError, TypeError, KeyError) as e:   # unreadable or malformed answer: served undated, never blocking
            x['dating'] = f'absent (GitHub not read: {str(e)[:80] or type(e).__name__}; check with repo-head {repo} before citing it under T)'; return x
        if why: return {'refusal': why, 'url': meta(url), 'repo': repo}
        x.update(sha=h['sha'], date=h['date'], id=f"repo:{repo}@{h['sha']}", dating='last commit of the default branch before T (repo-head barrier)')
        return x

    def search(self, arxiv, limit=5, B=None):
        arxiv = re.sub(r'(?i)^arxiv:\s*', '', str(arxiv).strip())          # the identity rule writes arxiv:<id>; the bare id is accepted too
        refuse(not re.fullmatch(r'\d{4}\.\d{4,5}(?:v\d+)?', arxiv), 'arxiv')
        arxiv = re.sub(r'v\d+$', '', arxiv)
        d = self.c.json('https://huggingface.co/api/papers/' + arxiv)
        p = d.get('paper', d)
        yy, mm = int(arxiv[:2]), int(arxiv[2:4])
        id_bound = (datetime.date(2000 + yy + (mm == 12), mm % 12 + 1, 1) - datetime.timedelta(days=1)).isoformat() if 1 <= mm <= 12 else None
        hf_date = p.get('publishedAt')
        date = min([x for x in (id_bound, str(hf_date)[:10] if hf_date else None) if x], default=None)
        x = dict(arxiv=arxiv, date=date, date_hf_published=hf_date, date_arxiv_id_bound=id_bound, models=[], datasets=[], spaces=[], repos=[])
        if id_bound and hf_date and str(hf_date)[:10] > id_bound:
            x['date_note'] = (f'Hugging Face publishedAt ({str(hf_date)[:10]}) is later than the month of the arXiv identifier (submitted by {id_bound}): '
                              'the earlier bound dates the paper')
        if p.get('githubRepo'):
            r = self._repo(p['githubRepo'], p.get('githubStars'), B)
            if 'refusal' in r: x['repos_refused'] = [r]
            else: x['repos'] = [r]
        else:
            x['repos_note'] = 'githubRepo not filled on Hugging Face Papers: the absence of official code is not established (search it by name)'
        import sources.hf as hf                                              # noqa: E402  (same dating as search-hf-models)
        budget = [int(CFG['paper_code']['legacy_lookups'])]
        returned = {}
        for kind in ('models', 'datasets', 'spaces'):
            items = self.c.json('https://huggingface.co/api/' + kind + '?' + urlencode({'filter': 'arxiv:' + arxiv, 'limit': limit, 'full': 'true',
                                                                                     'sort': CFG['paper_code']['sort'], 'direction': -1}))
            items = [i for i in items if isinstance(i, dict) and i.get('id')] if isinstance(items, list) else []
            returned[kind] = len(items)
            for i in items:
                url = 'https://huggingface.co/' + ('' if kind == 'models' else kind + '/') + i['id']
                base = dict(id=i.get('id'), url=url, stars=i.get('likes'), downloads=i.get('downloads'), stars_as_of='now (not as of T)', status='community_unverified')
                if B is not None and kind in ('models', 'datasets'):
                    it = hf.hf_item(i, kind, B, budget)
                    if it is None: continue                                    # created on/after T, or forbidden: removed and counted by the barrier
                    base.update(date=it['date'], date_created=it.get('date_created'), metadata=it.get('metadata'),
                                **{k: it[k] for k in ('licence', 'task', 'date_note') if it.get(k)})
                else:
                    created = i.get('createdAt')
                    base.update(date=None if str(created or '')[:10] == hf.HF_LEGACY else created, date_created=created,
                                metadata='licence, tags not served (lastModified is not a creation date)')
                x[kind].append(base)
        x['listing'] = {'sort': CFG['paper_code']['sort'] + ' desc', 'limit_per_kind': limit, 'returned': returned,
                        'note': 'a kind that returned the limit may hold more linked items (raise --n)'}
        return x


class Provenance:
    def __init__(self, client): self.c = client

    def _json(self, url):
        """SWH_TOKEN as Bearer (archive.softwareheritage.org only, never on a redirect); rejected (401/403) -> remembered as invalid,
        one retry without it, and the rest of the run goes on anonymously."""
        tok = swh_token(self.c.cache_dir)
        if tok:
            try: return self.c.json(url, tok, cred='SWH_TOKEN')
            except ValueError as e:
                if str(e) not in ('provider_error:HTTP401', 'provider_error:HTTP403'): raise
            mark_invalid(self.c.cache_dir, 'SWH_TOKEN')
        return self.c.json(url)

    def origins(self, q, limit=5): return self._json(SWH + 'api/1/origin/search/' + quote(q, safe='') + '/?' + urlencode({'limit': limit}))

    def visit(self, origin, T=None):
        """Visit of an origin: without T the latest one with a snapshot; with T (date of the question) the last visit with a snapshot
        dated before T (visit_before), never a later one."""
        refuse(not re.fullmatch(ORIGIN, origin), 'origin')
        if T is not None: return self.visit_before(origin, str(T)[:10])
        d = self._json(SWH + 'api/1/origin/' + quote(origin, safe='') + '/visit/latest/?require_snapshot=true')
        return self._visit_out(origin, d)

    @staticmethod
    def _visit_out(origin, d):
        snp = 'swh:1:snp:' + d['snapshot'] if d.get('snapshot') else None
        return dict(origin=origin, swhid=snp, date_visited=d.get('date'), status=d.get('status'), permanent_url=SWH + (snp or ''))

    def visit_before(self, origin, T):
        """Last visit with a snapshot dated before T (YYYY-MM-DD). The visit list is served newest first, software_heritage.visits_per_page
        per request, `last_visit=k` = the visits numbered below k: the first page, then a bisection on the visit number (visit dates grow
        with the number), at most software_heritage.visit_requests requests (config.json). None found -> refusal 'unavailable before T'."""
        cfg = CFG['software_heritage']; per, budget = int(cfg['visits_per_page']), int(cfg['visit_requests'])
        base = SWH + 'api/1/origin/' + quote(origin, safe='') + '/visits/?'
        page = lambda last: (lambda r: r if isinstance(r, list) else [])(self._json(base + urlencode(dict(per_page=per, **({'last_visit': last} if last else {})))))
        before = lambda v: bool(v.get('date')) and str(v['date'])[:10] < T
        best = lambda vs: next((v for v in vs if v.get('snapshot') and before(v)), None)   # newest first: the first match is the last before T
        newer = lambda a, b: b if a is None or (b is not None and b['visit'] > a['visit']) else a
        vs = page(None); n, cand, exact = 1, best(vs) if vs else None, True
        if not cand and len(vs) >= per:                                     # every visit of the first page is at/after T (or has no snapshot)
            lo, hi = 1, vs[-1]['visit']                                     # the answer is a visit numbered in [lo, hi)
            while lo < hi and n < budget:
                m = (lo + hi) // 2; vs = page(m + 1); n += 1                # visits numbered m and below, newest first
                if not vs: lo = m + 1; continue
                b = best(vs)
                if before(vs[0]): cand, lo = newer(cand, b), m + 1          # the page is before T: a later one may sit in (m, hi)
                elif b: cand, lo = newer(cand, b), hi                       # the page straddles T: its last visit before T is the answer
                else: hi = vs[-1]['visit']
            exact = lo >= hi
        if not cand:
            return {'refusal': f'unavailable before T: no Software Heritage visit with a snapshot dated before {T} found'
                               + ('' if exact else f' within {budget} visit-list requests (software_heritage.visit_requests)')}
        return dict(self._visit_out(origin, cand), visit=cand.get('visit'), selected='last visit with a snapshot before T'
                    + ('' if exact else f' found within {budget} requests (a later one before T may exist)'))

    def resolve(self, swhid):
        refuse(not re.fullmatch(SWHID, swhid), 'swhid')
        return self._json(SWH + 'api/1/resolve/' + quote(swhid, safe=':') + '/')

    def file(self, origin, sha, path):
        refuse(not re.fullmatch('[a-f0-9]{40}', sha) or path.startswith('/') or any(x in ('', '..', '.') for x in path.split('/')), 'reference')
        rev = self._json(SWH + 'api/1/revision/' + sha + '/')
        entry = self._json(SWH + 'api/1/directory/' + rev['directory'] + '/' + quote(path, safe='/') + '/?' + urlencode({'type': 'file'}))
        target = entry.get('target') or entry.get('checksums', {}).get('sha1_git')
        refuse(entry.get('type') != 'file' or not re.fullmatch('[a-f0-9]{40}', target or ''), 'not_file')
        return dict(origin=origin, swhid='swh:1:cnt:' + target, revision_swhid='swh:1:rev:' + sha, directory_swhid='swh:1:dir:' + rev['directory'],
                    date_visited=None, permanent_url=f'{SWH}swh:1:cnt:{target};origin={quote(origin, safe="")};anchor=swh:1:rev:{sha};path=/{quote(path, safe="/")}')

    def file_text(self, arg):
        """code-file <origin>#<path>@<40-hex SHA> -> the whole file at that revision (raw content of the archive, same client, same pacing,
        same size bound MAX_BYTES), dated by the commit (committer date, else author date) so that the gateway's date barrier applies.
        Read by tools/verifier.py when no local git directory holds the SHA (plugins/code.md, verification rule 1)."""
        m = re.fullmatch(CODE_FILE, arg or '')
        refuse(not m, 'reference')
        origin, path, sha = m.groups()
        rev = self._json(SWH + 'api/1/revision/' + sha + '/')
        f = self.file(origin, sha, path)
        target = f['swhid'].rsplit(':', 1)[1]
        url, tok = SWH + 'api/1/content/sha1_git:' + target + '/raw/', swh_token(self.c.cache_dir)
        data = None
        if tok:
            try: data = self.c.get(url, tok, cred='SWH_TOKEN')
            except ValueError as e:
                if str(e) not in ('provider_error:HTTP401', 'provider_error:HTTP403'): raise
                mark_invalid(self.c.cache_dir, 'SWH_TOKEN')
        if data is None: data = self.c.get(url)
        refuse(b'\0' in data, 'binary')
        return dict(f, id=f'{path}@{sha}', path=path, sha=sha, date=rev.get('committer_date') or rev.get('date'), bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(), text=data.decode('utf-8', 'replace'))



# ---------------------------------------------------------------- GitHub repository at a commit, engine `github-repo` (config.json github_repo)
GH_REPO = r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}'           # <owner>/<name>
DEPS_DEV_HOST = urlsplit(RM['deps_dev_projects']).hostname
GH_HOSTS = frozenset((GH_API_HOST, GH_RAW_HOST, DEPS_DEV_HOST))
GH_COMMIT_ABSENT = ('provider_error:HTTP404', 'provider_error:HTTP422')   # unknown or ambiguous commit on the named repository


def github_repo_of(origin):
    """<owner>/<name> of a GitHub origin URL (github_repo.web base; `.git` and a trailing slash dropped), else None."""
    o = str(origin or '').strip()
    if not o.startswith(GH['web']): return None
    rest = o[len(GH['web']):].rstrip('/').removesuffix('.git')
    return rest if re.fullmatch(GH_REPO, rest) and rest.split('/')[1] not in ('.', '..') else None


def path_ok(path):
    """A repository-relative file path: not absolute, no empty, '.' or '..' segment, no control character."""
    return isinstance(path, str) and bool(path) and not path.startswith('/') and not any(x in ('', '.', '..') for x in path.split('/')) \
        and not any(ord(c) < 32 for c in path)


RATE_FILE = 'github-rate-limited.json'   # in the state dir: {'until': epoch, 'until_utc'} of an exhausted GitHub API quota (no value of any key)


def meta(v):
    """A metadata string served to the model (branch, licence path or identifier, date): tags stripped, entities decoded, control characters
    and line breaks folded to spaces, cut at github_repo.metadata_chars; None stays None, a non-string is served as its text."""
    if v is None: return None
    t = ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', str(v))).translate({c: ' ' for c in range(32)}).split())
    return t[:int(GH['metadata_chars'])]


def repo_name(v, fallback):
    """A served <owner>/<name> (GH_REPO, no . or .. name), else the fallback (the name asked, already checked)."""
    v = str(v or '')
    return v if re.fullmatch(GH_REPO, v) and v.split('/')[1] not in ('.', '..') else fallback


# Opening words of the canonical licence texts (a vocabulary of titles, not a licence scanner): most specific first.
LICENCE_TEXTS = [
    ('AGPL-3.0', r'GNU\s+AFFERO\s+GENERAL\s+PUBLIC\s+LICENSE\s+Version\s+3'), ('LGPL-3.0', r'GNU\s+LESSER\s+GENERAL\s+PUBLIC\s+LICENSE\s+Version\s+3'),
    ('LGPL-2.1', r'GNU\s+LESSER\s+GENERAL\s+PUBLIC\s+LICENSE\s+Version\s+2\.1'), ('GPL-3.0', r'GNU\s+GENERAL\s+PUBLIC\s+LICENSE\s+Version\s+3'),
    ('GPL-2.0', r'GNU\s+GENERAL\s+PUBLIC\s+LICENSE\s+Version\s+2'), ('Apache-2.0', r'Apache\s+License,?\s+Version\s+2\.0'),
    ('MPL-2.0', r'Mozilla\s+Public\s+License,?\s+(?:v\.|version)\s*2\.0'), ('BUSL-1.1', r'Business\s+Source\s+License\s+1\.1'),
    ('PolyForm-Shield-1.0.0', r'PolyForm\s+Shield\s+License\s+1\.0\.0'), ('PolyForm-Noncommercial-1.0.0', r'PolyForm\s+Noncommercial\s+License\s+1\.0\.0'),
    ('Elastic-2.0', r'Elastic\s+License\s+2\.0'), ('SSPL-1.0', r'Server\s+Side\s+Public\s+License'), ('BSL-1.0', r'Boost\s+Software\s+License\s*-?\s*Version\s+1\.0'),
    ('CC0-1.0', r'CC0\s+1\.0\s+Universal'), ('Unlicense', r'This\s+is\s+free\s+and\s+unencumbered\s+software\s+released\s+into\s+the\s+public\s+domain'),
    ('ISC', r'Permission\s+to\s+use,\s+copy,\s+modify,\s+and(?:/or)?\s+distribute\s+this\s+software\s+for\s+any\s+purpose'),
    ('MIT', r'Permission\s+is\s+hereby\s+granted,\s+free\s+of\s+charge'),
    ('BSD-3-Clause', r'Redistribution\s+and\s+use\s+in\s+source\s+and\s+binary\s+forms(?=[\s\S]*Neither\s+the\s+name)'),
    ('BSD-2-Clause', r'Redistribution\s+and\s+use\s+in\s+source\s+and\s+binary\s+forms'),
]
LICENCE_TEXTS = [(k, re.compile(v, re.I)) for k, v in LICENCE_TEXTS]
SPDX_TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9.+-]*')


def licence_of_text(text):
    """Licences whose canonical opening words appear in a licence file -> sorted list (several = several texts in one file); [] = none
    recognised (a modified or custom text: to be read). BSD-2 is not reported when BSD-3 is."""
    t = str(text or '')[:int(GH['licence_read']['text_chars'])]
    ids = [k for k, rx in LICENCE_TEXTS if rx.search(t)]
    if 'BSD-3-Clause' in ids and 'BSD-2-Clause' in ids: ids.remove('BSD-2-Clause')
    if 'LGPL-3.0' in ids and 'GPL-3.0' in ids: ids.remove('GPL-3.0')
    if 'AGPL-3.0' in ids and 'GPL-3.0' in ids: ids.remove('GPL-3.0')
    return sorted(ids)


def spdx_expression(v):
    """A licence value that is an SPDX expression (identifiers joined by OR / AND / WITH, parentheses) -> the expression with its operators
    upper-cased; anything else (free text: 'Apache 2.0', 'BSD-like') -> None."""
    v = ' '.join(str(v or '').replace('(', ' ( ').replace(')', ' ) ').split())
    toks = v.split(' ') if v else []
    if not toks: return None
    out, want_id, depth = [], True, 0
    for t in toks:
        if t == '(' and want_id: depth += 1; out.append(t); continue
        if t == ')' and not want_id and depth: depth -= 1; out.append(t); continue
        if want_id and SPDX_TOKEN.fullmatch(t) and t.upper() not in ('OR', 'AND', 'WITH') and (any(c.isdigit() for c in t) or t in SPDX_BARE):
            out.append(t); want_id = False; continue
        if not want_id and t.upper() in ('OR', 'AND', 'WITH'): out.append(t.upper()); want_id = True; continue
        return None
    return ' '.join(out).replace('( ', '(').replace(' )', ')') if not want_id and not depth else None


SPDX_BARE = frozenset(('MIT', 'ISC', 'Unlicense', 'Zlib', 'WTFPL', 'MIT-0', '0BSD', 'Python-2.0', 'PSF-2.0', 'BlueOak-1.0.0'))


def spdx_members(expr):
    """Identifiers of an SPDX expression and its kind: ('or' | 'and' | 'single' | 'mixed', [ids]); -only / -or-later folded."""
    toks = [t for t in re.split(r'[\s()]+', str(expr or '')) if t]
    ops = {t.upper() for t in toks if t.upper() in ('OR', 'AND')}
    ids = [re.sub(r'-(?:only|or-later)$', '', t) for k, t in enumerate(toks)
           if t.upper() not in ('OR', 'AND', 'WITH') and not (k and toks[k - 1].upper() == 'WITH')]   # an exception after WITH is not a licence
    return ('single' if not ops else 'or' if ops == {'OR'} else 'and' if ops == {'AND'} else 'mixed'), ids


def manifest_licence(path, text):
    """The licence field of a manifest, as written (never executed: setup.py and gemspecs are read as text) -> str or None."""
    t, n = str(text or ''), path.rsplit('/', 1)[-1]
    if n in ('package.json', 'composer.json'):
        try: d = json.loads(t)
        except ValueError: return None
        v = d.get('license') if isinstance(d, dict) else None
        if isinstance(v, dict): v = v.get('type')
        if isinstance(v, list): v = ' OR '.join(str(x.get('type') if isinstance(x, dict) else x) for x in v)   # composer: a list = a choice
        if not v and isinstance(d, dict) and isinstance(d.get('licenses'), list):
            v = ' OR '.join(str(x.get('type') if isinstance(x, dict) else x) for x in d['licenses'])
        return str(v) if v else None
    m = re.search(r'^\s*license\s*=\s*\{[^}]*?\btext\s*=\s*["\']([^"\'\n]+)["\']', t, re.M | re.I) \
        or re.search(r'^\s*license\s*=\s*["\']([^"\'\n]+)["\']', t, re.M | re.I) \
        or (re.search(r'^\s*license\s*[=:]\s*([^\n#]+)$', t, re.M | re.I) if n == 'setup.cfg' else None) \
        or re.search(r'\blicen[cs]es?\s*=\s*\[?\s*["\']([^"\'\n]+)["\']', t)
    return m.group(1).strip() if m else None


class GitHubRepo:
    """GitHub REST API (keyless: GitHub documents github_repo.anonymous_requests_per_hour without a token; VP_GITHUB_TOKEN sent to the API host
    only when the key rule already resolves it, never logged) and raw files at a commit (raw host, never any credential): repository metadata,
    SPDX licence (at a commit with ref=), resolution of an abbreviated SHA to the full one ON THE NAMED repository (/commits/<sha> on
    <owner>/<name>; also /compare against the default branch, since GitHub serves the commits of a whole fork network), whole file at a 40-hex
    SHA. A rate-limited answer (429, or 403 with X-RateLimit-Remaining 0 / Retry-After) is typed `rate_limited`: no further GitHub API request
    in the process, nor (with a state dir) in any later process before the reset time, kept in <state>/github-rate-limited.json (X-RateLimit-Reset,
    else Retry-After, else github_repo.rate_limit_wait_s). Metadata strings are served plain and bounded (github_repo.metadata_chars); a full
    name that is not <owner>/<name> is replaced by the name asked. Answers memoised per instance (and cached by CodeClient with a state dir)."""
    def __init__(self, client, extra=None):
        self.c = client if GH_HOSTS <= client.hosts else CodeClient(hosts=client.hosts | GH_HOSTS, interval=client.interval, cache_dir=client.cache_dir, offline=client.offline)
        self.extra = extra if extra is not None else {}
        self.memo = {}
        self.canonical = {}   # asked <owner>/<name> (lower case) -> current <owner>/<name> after a followed redirection (raw files read there)

    @staticmethod
    def check(repo):
        refuse(not isinstance(repo, str) or not re.fullmatch(GH_REPO, repo) or repo.split('/')[1] in ('.', '..'), 'repository')
        return repo

    def _stopped_until(self):
        """Epoch seconds until which the GitHub API quota is known exhausted (this process, or <state>/RATE_FILE), else None."""
        if getattr(self.c, 'github_rate_limited', False): return getattr(self.c, 'github_rate_until', None) or float('inf')
        if not self.c.cache_dir: return None
        try: until = float(json.loads((self.c.cache_dir / RATE_FILE).read_text())['until'])
        except (OSError, ValueError, TypeError, KeyError): return None
        return until if until > time.time() else None

    def _stop(self):
        """Records the exhausted quota until its reset: in the process, and in the state dir for the next processes of the run."""
        until = self.c.rate_reset.get(GH_API_HOST) or int(time.time()) + int(GH['rate_limit_wait_s'])
        self.c.github_rate_limited, self.c.github_rate_until = True, until
        when = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(until))
        if self.c.cache_dir:
            (self.c.cache_dir / RATE_FILE).write_text(json.dumps({'until': until, 'until_utc': when}))
        self.extra['github_rate_limited'] = f'GitHub API quota exhausted: no further GitHub API request before {when} (reset)'

    def _api(self, path):
        until = self._stopped_until()
        if until:
            self.extra.setdefault('github_rate_limited', 'GitHub API quota exhausted: no GitHub API request before '
                                  + (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(until)) if until != float('inf') else 'the end of this process') + ' (reset)')
            refuse(True, 'rate_limited')
        url = GH['api'] + path
        if url in self.memo: return self.memo[url]
        try: tok = read_token()
        except ValueError: tok = None; self.extra['github_token'] = 'credential_invalid (not sent)'
        if tok and 'VP_GITHUB_TOKEN' in invalid_keys(self.c.cache_dir): tok = None

        def fetch(u):
            nonlocal tok
            if tok:
                try: return self.c.json(u, tok)
                except ValueError as e:
                    if str(e) != 'provider_error:HTTP401': raise
                    mark_invalid(self.c.cache_dir, 'VP_GITHUB_TOKEN'); self.extra['key_invalid_github'] = 'VP_GITHUB_TOKEN rejected (401): anonymous retry'
                    tok = None
                    return self.c.json(u)
            self.extra.setdefault('github_token', f"absent: anonymous ({GH['anonymous_requests_per_hour']} requests/h)")
            return self.c.json(u)
        hops, u = int(GH.get('follow_api_redirects') or 0), url
        try:
            for i in range(hops + 1):
                try: d = fetch(u); break
                except ValueError as e:
                    loc = self.c.redirects.pop(u, None) if str(e) == 'redirect_refused' else None
                    if not loc or i == hops or urlsplit(loc).hostname != GH_API_HOST: raise
                    asked = '/'.join(path.split('?')[0].split('/')[1:3]) if path.startswith('repos/') else path
                    self.extra.setdefault('repository_moved', f'GitHub redirects {asked} (renamed or transferred repository): followed on {GH_API_HOST} only, '
                                                         'answers served from the new location; cite the current <owner>/<name>')
                    u = loc
        except ValueError as e:
            if str(e) == 'rate_limited': self._stop()
            raise
        self.memo[url] = d
        return d

    def rate(self):
        """Core quota left (GET rate_limit, not counted by GitHub): {'limit', 'remaining', 'reset'}; None when unreadable. Asked with the token
        when one is loaded (the quota of the requests actually made; CodeClient sends it to the API host only), else anonymously."""
        live = CodeClient(hosts=self.c.hosts, interval=self.c.interval, offline=self.c.offline)   # never served from the HTTP cache
        live.sleep, live.clock = self.c.sleep, self.c.clock
        try: tok = read_token()
        except ValueError: tok = None
        if tok and 'VP_GITHUB_TOKEN' in invalid_keys(self.c.cache_dir): tok = None
        try: d = live.json(GH['api'] + 'rate_limit', tok)
        except (ValueError, RuntimeError): return None
        core = ((d or {}).get('resources') or {}).get('core') or {}
        return {k: core.get(k) for k in ('limit', 'remaining', 'reset')}

    def info(self, repo):
        """Current metadata (as of the call, not of T): full name, default branch, SPDX licence detected now, pushed_at, archived, fork, parent."""
        d = self._api('repos/' + self.check(repo))
        name = repo_name(d.get('full_name'), repo)
        if name.lower() != repo.lower():                                    # renamed or transferred (redirection followed on the API host)
            self.canonical[repo.lower()] = name
            self.extra['repository_moved'] = f'{repo} is now {name} (GitHub redirection followed on {GH_API_HOST}); files are read under {name}'
        return dict(repo=name, default_branch=meta(d.get('default_branch')), licence_spdx=meta((d.get('license') or {}).get('spdx_id')),
                    created_at=meta(d.get('created_at')), pushed_at=meta(d.get('pushed_at')), archived=d.get('archived'), fork=d.get('fork'),
                    parent=repo_name((d.get('parent') or {}).get('full_name'), None), url=GH['web'] + name)

    def licence(self, repo, ref=None):
        """Licence file detected by GitHub (at the commit `ref` when given): {'spdx', 'path', 'ref'}; spdx None when no licence file is detected,
        'NOASSERTION' when GitHub does not recognise it (then the file at `path` is to be read)."""
        refuse(ref is not None and not re.fullmatch(r'[0-9a-f]{7,40}', ref), 'sha')
        try: d = self._api('repos/' + self.check(repo) + '/license' + ('?' + urlencode({'ref': ref}) if ref else ''))
        except ValueError as e:
            if str(e) != 'provider_error:HTTP404': raise
            return dict(spdx=None, path=None, ref=ref, status='no licence file detected')
        return dict(spdx=meta((d.get('license') or {}).get('spdx_id')), path=meta(d.get('path')), ref=ref, status='detected')

    def commit(self, repo, sha):
        """Abbreviated or full SHA -> {'sha' (40 hex), 'date' (committer date), 'author_date'} as served by /commits on the named repository;
        unknown there -> ValueError('commit_not_in_repository')."""
        sha = str(sha or '').lower()
        refuse(not re.fullmatch(r'[0-9a-f]{7,40}', sha), 'sha')
        try: d = self._api('repos/' + self.check(repo) + '/commits/' + sha)
        except ValueError as e:
            refuse(str(e) in GH_COMMIT_ABSENT, 'commit_not_in_repository')
            raise
        full = str(d.get('sha') or '')
        refuse(not re.fullmatch(r'[0-9a-f]{40}', full) or not full.startswith(sha), 'commit_mismatch')
        c = d.get('commit') or {}
        parents = [str(x.get('sha')) for x in d.get('parents') or [] if isinstance(x, dict) and re.fullmatch(r'[0-9a-f]{40}', str(x.get('sha') or ''))]
        out = dict(sha=full, date=(c.get('committer') or {}).get('date'), author_date=(c.get('author') or {}).get('date'))
        if parents: out['parents'] = parents
        return out

    def in_default_branch(self, repo, sha, branch):
        """True when the commit is in the history of `branch` (/compare status behind or identical), False when it is not (ahead, diverged),
        None when GitHub cannot compare them (another network)."""
        refuse(not re.fullmatch(r'[0-9a-f]{40}', sha or '') or not branch, 'sha')
        try: d = self._api('repos/' + self.check(repo) + '/compare/' + quote(branch, safe='') + '...' + sha + '?' + urlencode({'per_page': 1}))
        except ValueError as e:
            if str(e) not in GH_COMMIT_ABSENT: raise
            return None
        st = d.get('status')
        return True if st in ('behind', 'identical') else False if st in ('ahead', 'diverged') else None

    def resolve(self, repo, sha):
        """Commit of the named repository: full SHA, date, whether it is in the default branch history, and the repository's creation date."""
        c = self.commit(repo, sha)
        out = dict(c, repo=repo, membership='served by /commits on the repository')
        info = self.info(repo); br = info.get('default_branch')
        anc = self.in_default_branch(repo, c['sha'], br) if br else None
        out.update(default_branch=br, in_default_branch=anc, repo_created_at=info.get('created_at'),
                   membership='in the default branch history' if anc else 'served by the repository but not in its default branch history (fork network or other branch)'
                   if anc is False else out['membership'])
        return out

    def head_before(self, repo, T, skip=()):
        """Last commit of the default branch dated before T (datetime.date of the question): GET /commits?sha=<default branch>&until=<T>
        (github_repo.head_candidates per page, newest first), the first whose committer date is before T, then resolved on the repository
        (resolve: /commits/<sha> and /compare) so that gate() decides as for any other commit. None when that page holds none."""
        br = self.info(repo).get('default_branch')
        refuse(not br, 'default_branch')
        d = self._api('repos/' + self.check(repo) + '/commits?' + urlencode({'sha': br, 'until': T.isoformat() + 'T00:00:00Z', 'per_page': int(GH['head_candidates'])}))
        for c in d if isinstance(d, list) else []:
            sha = str((c or {}).get('sha') or '') if isinstance(c, dict) else ''
            date = str(((c.get('commit') or {}).get('committer') or {}).get('date') or '') if sha else ''
            if re.fullmatch(r'[0-9a-f]{40}', sha) and sha not in skip and re.match(r'\d{4}-\d{2}-\d{2}', date) and date[:10] < T.isoformat():
                return self.resolve(repo, sha)
        return None

    def _blobs(self, repo, sha):
        """Every blob path of the commit (GET /git/trees/<sha>?recursive=1, memoised: the request of repo-tree): (paths, truncated by GitHub)."""
        refuse(not re.fullmatch(r'[0-9a-f]{40}', sha or ''), 'sha')
        d = self._api('repos/' + self.check(repo) + '/git/trees/' + sha + '?' + urlencode({'recursive': 1}))
        paths = [e['path'] for e in (d.get('tree') or []) if isinstance(e, dict) and e.get('type') == 'blob' and isinstance(e.get('path'), str)
                 and path_ok(e['path']) and len(e['path']) <= 300]
        return paths, bool(d.get('truncated'))

    def tree(self, repo, sha, prefix=''):
        """File paths of the commit (GET /git/trees/<sha>?recursive=1): blobs under `prefix`, repository-relative paths only (path_ok),
        at most github_repo.tree_paths_served; truncated when GitHub cut its own list or the cap was reached."""
        refuse(not re.fullmatch(r'[0-9a-f]{40}', sha or ''), 'sha')
        refuse(prefix and not path_ok(prefix.rstrip('/')), 'reference')
        allp, cut = self._blobs(repo, sha)
        pre = prefix.rstrip('/') + '/' if prefix else ''
        paths = [p for p in allp if p.startswith(pre)]
        cap = int(GH['tree_paths_served'])
        return dict(paths=paths[:cap], count=len(paths), truncated=cut or len(paths) > cap)

    def same_name(self, repo, sha, name):
        """Paths of the commit whose file name is `name` (same /git/trees request as tree(), memoised; no cap on the search, so a large repository
        is searched whole): dict(paths=[...], count=n, truncated=True when GitHub cut its own list). Used to locate a mis-cited path."""
        refuse(not re.fullmatch(r'[0-9a-f]{40}', sha or ''), 'sha')
        refuse(not name or '/' in name or not path_ok(name), 'reference')
        allp, cut = self._blobs(repo, sha)
        paths = [p for p in allp if p.rsplit('/', 1)[-1] == name]
        return dict(paths=paths, count=len(paths), truncated=cut)

    def licence_read(self, repo, sha, detected=None):
        """The licence files of the commit READ, not judged (audit 2026-10-31, item 3a: GitHub answers NOASSERTION for a dual licence, a
        modified MIT, a licence per directory; a missing LICENSE leaves only the README). From the tree at the 40-hex SHA (one API request,
        shared with repo-tree) and raw files at that SHA (raw host, no API quota, no credential), bounded by config.json github_repo.licence_read:
          files         licence files at the root (names starting with licence_read.file_prefixes: LICENSE, LICENCE, COPYING...), each
                        identified by the opening words of a licence text (LICENCE_TEXTS: a vocabulary of the canonical titles, not a scanner)
          manifest      the licence field of the root manifests (Cargo.toml, pyproject.toml, package.json, setup.cfg, setup.py,
                        composer.json, *.gemspec...: licence_read.manifests), as written, and as an SPDX expression when it is one
          by_directory  licence files below the root outside vendored copies, tests, docs and licence collections (implementations.
                        vendored_paths / excluded_paths, licence_read.skip_dirs), one entry per directory, shallowest first (its files, the
                        licences they hold, same_as_root): a
                        directory under its own licence (e.g. a platform/ under another licence than the rest) makes the licence depend
                        on the path of the mechanism
          readme        the lines of the root README that mention a licence (text only, at most licence_read.readme_lines)
          expression    the SPDX expression of the manifest when there is one ("MIT OR Apache-2.0": a dual licence kept whole), else the
                        single licence identified at the root, else None; `basis` says which
        -> dict; status 'read' (a licence file or a manifest field read), else 'unread' (then the licence is SOURCE-UNAVAILABLE)."""
        L = GH['licence_read']
        paths, cut = self._blobs(repo, sha)
        pre = tuple(x.upper() for x in L['file_prefixes'])
        name = lambda p: p.rsplit('/', 1)[-1]
        is_lic = lambda p: name(p).upper().startswith(pre) and not name(p).lower().endswith(tuple(L['skip_suffixes']))
        root = [p for p in paths if '/' not in p and is_lic(p)]
        skip = '|'.join(x for x in (IMPL['vendored_paths'], IMPL['excluded_paths'], L.get('skip_dirs') or '') if x)   # vendored copies, tests, docs
        sub = [p for p in paths if '/' in p and is_lic(p) and not (skip and re.search(skip, p))]
        mans = [p for p in paths if '/' not in p and (p in L['manifests'] or any(p.endswith(x) for x in L['manifest_suffixes']))]
        readme = next((p for p in sorted(paths) if '/' not in p and p.upper().startswith('README')), None)
        budget = [int(L['max_files'])]

        def text(p):
            if budget[0] <= 0: return None
            budget[0] -= 1
            try: return self.file(repo, sha, p)['text']
            except ValueError: return None
        out = dict(repo=repo, sha=sha, detected_by_github=detected, files=[], manifest=[], by_directory=[], readme=[], tree_truncated=cut)
        for p in sorted(root):
            t = text(p); out['files'].append(dict(path=p, identified=licence_of_text(t) if t is not None else None, read=t is not None))
        for p in sorted(mans):
            t = text(p)
            if t is None: continue
            v = manifest_licence(p, t)
            if v: out['manifest'].append(dict(path=p, value=meta(v), spdx_expression=spdx_expression(v)))
        groups = {}
        for p in sorted(sub): groups.setdefault(p.rsplit('/', 1)[0], []).append(p)
        root_ids = sorted({x for f in out['files'] for x in (f['identified'] or [])})
        for dname in sorted(groups, key=lambda x: (x.count('/'), x))[:int(L['by_directory_max'])]:   # one entry per directory, shallowest first
            ids, read = set(), []
            for p in groups[dname]:
                t = text(p)
                if t is not None: read.append(p); ids |= set(licence_of_text(t))
            out['by_directory'].append(dict(directory=dname, paths=groups[dname], identified=sorted(ids) if read else None,
                                            same_as_root=bool(read) and sorted(ids) == root_ids))
        if len(groups) > int(L['by_directory_max']): out['by_directory_more'] = len(groups) - int(L['by_directory_max'])
        if readme:
            t = text(readme)
            if t: out['readme'] = [dict(path=readme, line=i, text=meta(l)) for i, l in enumerate(t.split('\n'), 1) if re.search(r'licen[cs]', l, re.I)][:int(L['readme_lines'])]
        exprs = [m['spdx_expression'] for m in out['manifest'] if m['spdx_expression']]
        ids = sorted({x for f in out['files'] for x in (f['identified'] or [])})
        if exprs: out.update(expression=exprs[0], basis='manifest ' + next(m['path'] for m in out['manifest'] if m['spdx_expression']))
        elif len(ids) == 1: out.update(expression=ids[0], basis='licence file at the root (opening words of the text)')
        elif len(ids) > 1: out.update(expression=None, basis=f'several licences in the root files ({", ".join(ids)}): OR (choice) or AND (both) is not decided here, read them')
        elif detected and detected not in ('NOASSERTION', 'NONE'): out.update(expression=detected, basis='GitHub licence detection')
        else: out.update(expression=None, basis='no licence identified at the root')
        out['status'] = 'read' if out['expression'] or any(f['read'] for f in out['files']) or out['manifest'] else 'unread'
        if any(not d['same_as_root'] for d in out['by_directory']):
            out['note'] = 'licence files below the root that differ from the root: the licence of a mechanism depends on its path (by_directory)'
        if out['status'] == 'unread': out['note'] = ('no licence file nor manifest licence at the commit' + ('; the README mentions a licence (text above), which is not a licence file' if out['readme'] else ''))
        return out

    @staticmethod
    def gate(r, T):
        """Date barrier of a resolved commit (repo-file, code-file, repo-info with a SHA), T = datetime.date of the question: a refusal
        text, or None when the commit may be dated by its committer date. Refused: a commit not in the default branch history (False, or None
        when GitHub cannot compare: a fork of the network can push a backdated commit that /commits serves on the original repository), and a
        repository created on/after T (or undated). Residual limit: the committer date of an accepted commit stays falsifiable (set by git)."""
        if r.get('in_default_branch') is not True:
            return 'commit not in the default branch history of the repository (fork network, other branch, or not comparable): its date is not trusted'
        try: created = datetime.date.fromisoformat(str(r.get('repo_created_at') or '')[:10])
        except ValueError: created = None
        if created is None or created >= T: return 'repository created on/after T (or undated)'
        return None

    def backdate(self, repo, r, T, only=None):
        """Signals that a commit accepted by gate() entered the default branch on/after T although its committer date is before T (a backdated
        commit pushed after T: security review of 2026-10-31, item 2, residual limit). Only public, keyless GitHub REST answers, no
        circumvention; each check is listed in github_repo.backdate_checks (config.json) and costs at most one request:
          dates  : committer date earlier than the author date (git never does this by itself)            -> suspect (no request)
          parent : a parent of the commit has a committer date on/after T, or later than the commit's    -> definitive / suspect
          pulls  : GET /commits/<sha>/pulls: the earliest pull request merged into the default branch
                   that carries the commit was merged on/after T (none merged before T)                  -> definitive
          events : GET /events (GitHub keeps github_repo.events_window_days of public events): a push to
                   the default branch whose head is the commit, made on/after T                            -> definitive
        -> {'verdict': 'entered_after_T' | 'suspect' | 'unverified' | 'none_detected', 'signals': [...], 'checks': {check: status}, 'residual': text}.
        A check that cannot run (rate limit, transport) is recorded as such, never a refusal by itself, and never a negative either: without a
        definitive or suspect signal the verdict is then 'unverified' (Codex review 2026-10-31, item 1), not 'none_detected'. An events signal
        carries `before`, the head of the default branch before that push (PushEvent payload), when GitHub gives it."""
        sha, Ts = r.get('sha'), T.isoformat()
        signals, checks = [], {}
        add = lambda kind, strength, why: signals.append({'check': kind, 'strength': strength, 'evidence': meta(why)})
        day = lambda v: str(v or '')[:10] if re.match(r'\d{4}-\d{2}-\d{2}', str(v or '')) else None
        for chk in (GH.get('backdate_checks') if only is None else only) or ():   # only: a subset asked by the caller (forks-ahead: dates only per commit)
            try:
                if chk == 'dates':
                    a, c = str(r.get('author_date') or ''), str(r.get('date') or '')
                    checks[chk] = 'done'
                    if a and c and c < a: add(chk, 'suspect', f'committer date {c} earlier than author date {a}')
                elif chk == 'parent':
                    ps = r.get('parents') or []
                    if not ps: checks[chk] = 'no parent listed'; continue
                    pc = self.commit(repo, ps[0]); pd = day(pc.get('date')); checks[chk] = 'done'
                    if pd and pd >= Ts: add(chk, 'definitive', f'first parent {ps[0][:12]} has committer date {pc.get("date")} on/after T: the commit was made after T')
                    elif pc.get('date') and r.get('date') and str(pc['date']) > str(r['date']):
                        add(chk, 'suspect', f'first parent {ps[0][:12]} is dated {pc["date"]}, later than the commit ({r["date"]})')
                elif chk == 'pulls':
                    d = self._api('repos/' + self.check(repo) + '/commits/' + sha + '/pulls?' + urlencode({'per_page': int(GH['backdate_pulls'])}))
                    br = r.get('default_branch')
                    merged = sorted(str(x.get('merged_at')) for x in d if isinstance(x, dict) and x.get('merged_at')
                                    and (not br or ((x.get('base') or {}).get('ref') == br))) if isinstance(d, list) else []
                    checks[chk] = 'done'
                    if merged and merged[0][:10] >= Ts: add(chk, 'definitive', f'first pull request carrying the commit merged into the default branch on {merged[0]} (on/after T)')
                elif chk == 'events':
                    if (datetime.date.today() - T).days > int(GH['events_window_days']):
                        checks[chk] = f"not observable (T older than the {GH['events_window_days']} days of public events GitHub keeps)"; continue
                    d = self._api('repos/' + self.check(repo) + '/events?' + urlencode({'per_page': 100}))
                    br = r.get('default_branch'); checks[chk] = 'done'
                    for e in d if isinstance(d, list) else []:
                        pl = (e or {}).get('payload') or {} if isinstance(e, dict) else {}
                        if e.get('type') == 'PushEvent' and pl.get('head') == sha and (not br or pl.get('ref') == 'refs/heads/' + br) and (day(e.get('created_at')) or '') >= Ts:
                            add(chk, 'definitive', f'push of the commit to the default branch on {e.get("created_at")} (on/after T)')
                            before = str(pl.get('before') or '')
                            if re.fullmatch(r'[0-9a-f]{40}', before) and before.strip('0'): signals[-1]['before'] = before
                            break
                else: checks[chk] = 'unknown check (config.json github_repo.backdate_checks)'
            except Exception as e:                                      # a signal, never a blocker: any failure is recorded by its code or type
                checks[chk] = f"not run ({e if isinstance(e, (ValueError, RuntimeError)) else type(e).__name__})"
        unrun = any(str(v).startswith('not run') for v in checks.values())
        verdict = 'entered_after_T' if any(x['strength'] == 'definitive' for x in signals) else 'suspect' if signals else 'unverified' if unrun else 'none_detected'
        return {'verdict': verdict, 'signals': signals, 'checks': checks,
                'residual': 'the committer date is set by git: a backdated commit pushed on/after T is caught only by the signals above; '
                            'none detected is not a proof of a push before T'}

    def head_gated(self, repo, B, extra=None):
        """The last commit of the default branch dated before T that passes barrier(), at most github_repo.head_backdate_retries further
        candidates after a refusal by the backdate checks (Codex review 2026-10-31, item 1: skipping a late head does not make its ancestors
        safe, they may come from the same push):
          - refused by pull requests merged on/after T only: the next commit listed before T is tried (the other commits of such a pull
            request carry it too, each is refused by its own pulls check);
          - refused by a push on/after T: the head of the default branch BEFORE that push (PushEvent `before`) is tried, never an older
            commit of the list; without `before`, or when that head is dated on/after T, refused;
          - refused by any other definitive signal (a parent dated on/after T): refused, the head at T is not established;
          - a candidate tried after a refusal is accepted only when all its backdate checks ran (verdict not 'unverified').
        -> (commit, None) or (None, refusal text)."""
        skip, why, nxt = [], None, None
        for _ in range(1 + int(GH['head_backdate_retries'])):
            if nxt:
                h = self.resolve(repo, nxt); nxt = None
                if not str(h.get('date') or '')[:10] < B.T.isoformat():
                    return None, why + '; the head of the default branch before that push is dated on/after T: the head at T is not established'
            else: h = self.head_before(repo, B.T, skip)
            if h is None: break
            why = self.barrier(repo, h, B, extra)
            if not why:
                if skip and (h.get('backdate_check') or {}).get('verdict') == 'unverified':
                    return None, f"after {len(skip)} candidate(s) refused as entered on/after T, the next one ({h['sha'][:12]}) could not be fully checked " \
                                 f"(backdate checks not run): the head at T is not established"
                return h, None
            if 'entered the default branch on/after T' not in why: return None, why
            skip.append(h['sha'])
            sigs = [x for x in (h.get('backdate_check') or {}).get('signals') or [] if x.get('strength') == 'definitive']
            if {x['check'] for x in sigs} == {'pulls'}: continue
            nxt = next((x['before'] for x in sigs if x['check'] == 'events' and x.get('before')), None)
            if nxt and nxt not in skip: continue
            return None, why + '; the commits listed before it may come from the same push: not tried (the head at T is not established)'
        tried = f' ({len(skip)} candidate(s) refused as entered on/after T: ' + why + ')' if skip else ''
        return None, f"no commit of the default branch dated before T among the {GH['head_candidates']} newest listed before T (github_repo.head_candidates){tried}"

    def barrier(self, repo, r, B, extra=None, date_check=True):
        """The barrier of a resolved commit (repo-head, repo-tree, repo-file, repo-info @SHA, code-file, find-implementations): gate() (default
        branch history, repository created before T), then B.ok on the committer date, then backdate(): definitive evidence that the commit
        entered the default branch on/after T = refusal; a suspect signal = served, with a warning in `extra`; r gains `backdate_check`
        (verdict, signals, checks run, residual limit). date_check False: the committer date is left to the gateway date filter (repo-file,
        code-file: refusal 'after T'), and a commit dated on/after T spends no backdate request. -> a refusal text, or None."""
        extra = self.extra if extra is None else extra
        why = self.gate(r, B.T)
        if why: return 'after T or not datable: ' + why
        if date_check and not B.ok(None, r.get('date')): return 'after T: commit dated on/after T (or undated)'
        if not date_check and not str(r.get('date') or '')[:10] < B.T.isoformat(): return None   # refused by the gateway date filter: no request spent
        bd = self.backdate(repo, r, B.T)
        r['backdate_check'] = bd                                            # kept on a refusal too: head_gated reads its signals
        if bd['verdict'] == 'entered_after_T':
            return 'after T: committer date before T but the commit entered the default branch on/after T (' + \
                '; '.join(x['evidence'] for x in bd['signals'] if x['strength'] == 'definitive') + ')'
        w = {'suspect': 'possibly backdated commit (committer date before T, signals in backdate_check): its date before T is not established',
             'unverified': 'backdate checks not all run (backdate_check.checks): that the commit entered the default branch before T is not established'}.get(bd['verdict'])
        if w: extra['warning'] = (extra['warning'] + ' | ' + w) if extra.get('warning') else w
        return None

    def project(self, repo):
        """deps.dev project github.com/<owner>/<name> (config repo_metadata.deps_dev_projects, keyless): licence and OpenSSF Scorecard
        (overall score and its date), observed now; unavailable -> {'status': 'unavailable', 'reason'} (never blocks repo-info)."""
        try: d = self.c.json(RM['deps_dev_projects'] + quote(urlsplit(GH['web']).hostname + '/' + self.check(repo), safe=''))
        except (ValueError, RuntimeError) as e: return {'status': 'unavailable', 'reason': str(e)}
        sc_ = d.get('scorecard') or {}
        return {'status': 'ok', 'licence': meta(d.get('license')), 'scorecard_score': sc_.get('overallScore'), 'scorecard_date': sc_.get('date'),
                'stars': d.get('starsCount'), 'source': 'deps.dev'}

    def file(self, repo, sha, path):
        """Whole file at a 40-hex SHA (raw host, no credential): {'text', 'bytes', 'sha256', 'permanent_url'}; absent -> ValueError('file_not_found')."""
        refuse(not re.fullmatch(r'[0-9a-f]{40}', sha or ''), 'sha')
        refuse(not path_ok(path), 'reference')
        here = self.canonical.get(self.check(repo).lower(), repo)
        url = GH['raw'] + here + '/' + sha + '/' + quote(path, safe='/')
        if url not in self.memo:
            try: self.memo[url] = self.c.get(url)
            except ValueError as e:
                if str(e) == 'redirect_refused' and here == repo and int(GH.get('follow_api_redirects') or 0):   # renamed: learn the name on the API host
                    self.c.redirects.pop(url, None)
                    if self.info(repo)['repo'].lower() != repo.lower(): return self.file(repo, sha, path)
                refuse(str(e) == 'provider_error:HTTP404', 'file_not_found')
                raise
        data = self.memo[url]
        refuse(b'\0' in data, 'binary')
        return dict(text=data.decode('utf-8', 'replace'), bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                    permanent_url=GH['web'] + here + '/blob/' + sha + '/' + quote(path, safe='/'))

    def file_at(self, repo, sha, path):
        """code-file / repo-file: the commit resolved on the named repository (dated, membership), then the whole file at its full SHA."""
        r = self.resolve(repo, sha)
        f = self.file(repo, r['sha'], path)
        return dict(f, id=f"repo:{repo}/{path}@{r['sha']}", repo=repo, path=path, sha=r['sha'], date=r['date'], origin=GH['web'] + repo,
                    membership=r['membership'], in_default_branch=r.get('in_default_branch'), repo_created_at=r.get('repo_created_at'),
                    author_date=r.get('author_date'), default_branch=r.get('default_branch'), **({'parents': r['parents']} if r.get('parents') else {}),
                    method='github raw at the SHA')


OSV = 'https://api.osv.dev/v1/'
OSV_ECOSYSTEM = {'pypi': 'PyPI', 'npm': 'npm', 'cargo': 'crates.io', 'go': 'Go', 'maven': 'Maven', 'rubygems': 'RubyGems', 'nuget': 'NuGet', 'packagist': 'Packagist'}
OSV_FORM = r'(pypi|npm|cargo|go|maven|rubygems|nuget|packagist):([@A-Za-z0-9][\w.+\-/:]{0,200})@([A-Za-z0-9][\w.+\-]{0,100})'
OSV_ID = r'[A-Za-z][A-Za-z0-9]{1,15}-[A-Za-z0-9._:-]{2,60}'


class Vulns:
    """OSV.dev (keyless): advisories of package@version (POST /v1/query, raw records, dated by the gateway) and one advisory by id."""
    def __init__(self, client): self.c = client

    def query(self, system, package, version):
        refuse(system not in OSV_ECOSYSTEM or any(x in ('', '.', '..') for x in re.split(r'[/:]', package)) or version in ('.', '..'), 'reference')
        body = json.dumps({'package': {'name': package, 'ecosystem': OSV_ECOSYSTEM[system]}, 'version': version}).encode()
        return self.c.json(OSV + 'query', body=body).get('vulns') or []

    def get(self, ident):
        refuse(not re.fullmatch(OSV_ID, ident), 'osv_id')
        return self.c.json(OSV + 'vulns/' + quote(ident, safe=''))

    def query_commit(self, sha):
        """Advisories whose affected ranges contain this commit (POST config repo_metadata.osv_query with {"commit": <40-hex SHA>})."""
        refuse(not re.fullmatch(r'[0-9a-f]{40}', sha or ''), 'sha')
        return self.c.json(RM['osv_query'], body=json.dumps({'commit': sha}).encode()).get('vulns') or []


# ---------------------------------------------------------------- package usage (ecosyste.ms), engine `usage` (plugins/code.md)
USAGE_HOSTS = frozenset(('packages.ecosyste.ms', urlsplit(RM['ecosystems_repos']).hostname))
USAGE_REGISTRY = {'pypi': 'pypi.org', 'npm': 'npmjs.org', 'cargo': 'crates.io', 'go': 'proxy.golang.org', 'maven': 'repo1.maven.org',
                  'rubygems': 'rubygems.org', 'nuget': 'nuget.org', 'packagist': 'packagist.org', 'hex': 'hex.pm', 'pub': 'pub.dev', 'cran': 'cran.r-project.org'}
USAGE_FORM = r'(' + '|'.join(USAGE_REGISTRY) + r'):(@?[A-Za-z0-9][\w.+:-]*(?:/[A-Za-z0-9][\w.+:-]*){0,6})'   # Maven group:artifact, npm @scope/name, Go module paths (deep sub-modules)
USAGE = CFG['usage']
PRERELEASE = re.compile(r'(?i)(?:^|[-.+_]|\d)(?:alpha|beta|rc|pre|preview|dev|snapshot|canary|nightly|a|b)\.?\d*(?:$|[-.+_])')
USAGE_FORM_MSG = 'expected form <' + '|'.join(USAGE_REGISTRY) + '>:<package>'


def is_prerelease(number):
    """A version number marked as a pre-release (alpha, beta, rc, dev, preview, snapshot, a1, b2...), by its spelling only."""
    return bool(PRERELEASE.search(str(number or '')))


def version_key(number):
    """Sort key of a version number: its leading numeric components (1.10.2 > 1.9.7); None when it has none."""
    m = re.match(r'v?(\d+(?:\.\d+)*)', str(number or ''))
    return tuple(int(x) for x in m.group(1).split('.')) if m else None


SPDX_KNOWN = ('MIT', 'Apache-2.0', 'BSD-2-Clause', 'BSD-3-Clause', 'ISC', 'MPL-2.0', 'GPL-2.0', 'GPL-3.0', 'LGPL-2.1', 'LGPL-3.0', 'AGPL-3.0',
              'GPL-2.0-only', 'GPL-2.0-or-later', 'GPL-3.0-only', 'GPL-3.0-or-later', 'LGPL-2.1-only', 'LGPL-2.1-or-later', 'LGPL-3.0-only',
              'LGPL-3.0-or-later', 'AGPL-3.0-only', 'AGPL-3.0-or-later', 'Unlicense', 'CC0-1.0', 'BSL-1.0', 'EPL-2.0', 'Zlib', 'BUSL-1.1',
              'Elastic-2.0', 'SSPL-1.0', '0BSD', 'MIT-0', 'Python-2.0', 'PSF-2.0', 'CC-BY-4.0', 'CC-BY-SA-4.0', 'WTFPL', 'EUPL-1.2', 'OSL-3.0')


def spdx_canonical(v):
    """A licence identifier in another case ('agpl-3.0' from ecosyste.ms) -> its canonical SPDX spelling; unknown -> None."""
    return next((k for k in SPDX_KNOWN if k.lower() == str(v or '').strip().lower()), None)


class Usage:
    """packages.ecosyste.ms (data CC BY-SA 4.0, keyless common pool): current usage counts and the releases published before a date.
    Never decides the barrier: returns the dates, gateway.code_usage applies it."""
    def __init__(self, client):
        self.c = client if USAGE_HOSTS <= client.hosts else CodeClient(hosts=client.hosts | USAGE_HOSTS, interval=client.interval, cache_dir=client.cache_dir, offline=client.offline)

    def lookup(self, system, package, before):
        refuse(system not in USAGE_REGISTRY, 'system')
        refuse(not re.fullmatch(r'\d{4}-\d{2}-\d{2}', before), 'date')
        refuse(not re.fullmatch(r'@?[A-Za-z0-9][\w.+:-]{0,200}(/[A-Za-z0-9][\w.+:-]{0,200}){0,6}', package) or any(s in ('.', '..') for s in package.split('/')), 'reference')
        p = quote(package, safe='')                                         # npm @scope/name, Go and Maven paths: one URL segment
        root = f'https://packages.ecosyste.ms/api/v1/registries/{USAGE_REGISTRY[system]}/packages/{p}'
        d = self.c.json(root)
        vs = self.c.json(root + '/versions?' + urlencode({'published_before': before, 'sort': 'published_at', 'order': 'desc', 'per_page': 100}))
        return dict(package=package, system=system, registry=USAGE_REGISTRY[system], purl=d.get('purl'), repository_url=meta(d.get('repository_url')),
                    first_release_date=d.get('first_release_published_at'),
                    releases_before_T=[dict(number=meta(v.get('number')), date=v.get('published_at'), prerelease=is_prerelease(v.get('number')))
                                       for v in vs if isinstance(v, dict)],
                    dependent_packages_count=d.get('dependent_packages_count'), dependent_repos_count=d.get('dependent_repos_count'),
                    docker_dependents_count=d.get('docker_dependents_count'), downloads=d.get('downloads'), downloads_period=d.get('downloads_period'),
                    maintainers=[dict(login=m.get('login'), role=m.get('role')) for m in d.get('maintainers') or [] if isinstance(m, dict)],
                    licenses=d.get('licenses'), source='packages.ecosyste.ms (CC BY-SA 4.0, attribution: ecosyste.ms)')

    def dependents(self, system, package):
        """Dependent packages (names, repositories, first release), ONE request of packages.ecosyste.ms .../dependent_packages (config usage:
        dependents_per_page, sorted by dependents_sort desc), observed now: the dependency itself is current, never dated (the caller keeps
        the dependents whose first release is before T and marks them). Never decides the barrier."""
        p = quote(package, safe='')
        url = f'https://packages.ecosyste.ms/api/v1/registries/{USAGE_REGISTRY[system]}/packages/{p}/dependent_packages?' + \
            urlencode({'per_page': int(USAGE['dependents_per_page']), 'sort': USAGE['dependents_sort'], 'order': 'desc'})
        d = self.c.json(url)
        return [dict(name=meta(x.get('name')), repository_url=meta(x.get('repository_url')), first_release_date=x.get('first_release_published_at'),
                     downloads=x.get('downloads')) for x in d if isinstance(x, dict) and x.get('name')] if isinstance(d, list) else []

    def repository(self, repo):
        """ecosyste.ms repository lookup by URL (config repo_metadata.ecosystems_repos; GitHub repository <owner>/<name>): licence, dates,
        archived, fork, stars, default branch, as observed now. Never decides the barrier (gateway.code_usage applies it to created_at)."""
        GitHubRepo.check(repo)
        d = self.c.json(RM['ecosystems_repos'] + '?' + urlencode({'url': GH['web'] + repo}))
        lic = meta(d.get('license'))
        return dict(repository=repo_name(d.get('full_name'), repo), url=GH['web'] + repo, licence=lic, licence_spdx=spdx_canonical(lic), created_at=meta(d.get('created_at')),
                    pushed_at=meta(d.get('pushed_at')), archived=d.get('archived'), fork=d.get('fork'), stars=d.get('stargazers_count'),
                    default_branch=meta(d.get('default_branch')), source='repos.ecosyste.ms (CC BY-SA 4.0, attribution: ecosyste.ms)')


# ---------------------------------------------------------------- implementations of X in other repositories (config.json implementations)
IMPL = CFG['implementations']


def _alternatives(arg):
    """find-implementations pattern: literals separated by ' OR ' (upper case, spaces around) -> list of distinct literals, at most
    implementations.max_alternatives, each checked like a search-code query; ValueError('query_invalid' | 'too_many_alternatives')."""
    alts = []
    for a in (x.strip() for x in str(arg or '').split(' OR ')):
        if a and a.lower() not in [x.lower() for x in alts]: alts.append(a)
    refuse(not alts, 'query_invalid')
    refuse(len(alts) > int(IMPL['max_alternatives']), 'too_many_alternatives')
    for a in alts: check_query(a)
    return alts


def _content(alts):
    q = ['content:"' + a.replace('\\', '\\\\').replace('"', '\\"') + '"' for a in alts]
    return q[0] if len(q) == 1 else '(' + ' OR '.join(q) + ')'


def _norm(line):
    return ' '.join(str(line or '').lower().split())


class Implementations:
    """How other projects implement X (internal code bench 2026-10-31, case C2: 2 expected repositories of 5 found by hand-made search-code calls).
    Mechanical pipeline, every bound in config.json `implementations`:
      1. universe (optional): the most used packages of an ecosystem (ecosyste.ms, sorted by implementations.universe_sort, observed now) mapped
         to their GitHub repositories; one Sourcegraph query restricted to them (repo:^github\\.com/(a/b|c/d|...)$), so that "widely used"
         libraries are searched whatever their rank in the global index;
      2. global: one Sourcegraph query over the whole public index (forks and archived repositories excluded by Sourcegraph);
      3. GitHub code search (only with VP_GITHUB_TOKEN; keyless = 401, skipped and said);
      Sourcegraph queries exclude the non-implementation paths (implementations.excluded_paths: tests, docs, examples) and keep the language.
      4. grouping by repository; copies removed from the distinct count: GitHub forks, vendored copies (implementations.vendored_paths:
         vendor/, _vendor/, third_party/, node_modules/...; attributed to the upstream repository when it is in the list) and repositories whose
         matching files are the same as another repository's (same file name and same matching lines);
      5. ranking: repositories of the universe first, by their rank in the ecosystem, then the others by stars (Sourcegraph repoStars, observed now);
      6. per repository the best implementation file (most matching lines outside vendored paths) cited `repo:<owner>/<name>/<path>@<SHA40>`
         with its lines; the first implementations.pinned_repos (pinned_repos_with_token with a token) are dated on GitHub through the same
         barrier as repo-file (GitHubRepo.barrier); an indexed commit on/after T is replaced by the last commit of the default branch before T;
         the lines served are always looked up again in the file at the dated commit (never the provider's text). The other repositories keep
         the indexed commit (index_commit), marked undated, without any citation form (no cite, id nor permanent_url). A same-content copy of
         a repository refused at dating comes back as a candidate.
    A match is not an implementation: the file must be read (repo-file) before any claim."""
    def __init__(self, client, extra=None):
        hosts = client.hosts | GH_HOSTS | USAGE_HOSTS | {'sourcegraph.com'}
        self.c = client if hosts <= client.hosts else CodeClient(hosts=hosts, interval=client.interval, cache_dir=client.cache_dir, offline=client.offline)
        if self.c is not client: self.c.sleep, self.c.clock = client.sleep, client.clock
        self.extra = extra if extra is not None else {}
        self.gh, self.cs = GitHubRepo(self.c, self.extra), CodeSearch(self.c)
        self.status = {}

    def universe(self, ecosystem):
        """[(repo, rank, package)] of the implementations.universe_packages most used packages of the ecosystem (ecosyste.ms, pages of
        implementations.universe_page_size, sorted by implementations.universe_sort desc; observed now), GitHub repositories only, distinct."""
        refuse(ecosystem not in USAGE_REGISTRY, 'ecosystem')
        size, total = int(IMPL['universe_page_size']), int(IMPL['universe_packages'])
        out, seen, rank, skipped = [], set(), 0, 0
        for page in range(1, -(-total // size) + 1):
            url = f'https://packages.ecosyste.ms/api/v1/registries/{USAGE_REGISTRY[ecosystem]}/packages?' + \
                urlencode({'sort': IMPL['universe_sort'], 'order': 'desc', 'per_page': size, 'page': page})
            try: d = self.c.json(url)
            except (ValueError, RuntimeError) as e:
                self.status['universe'] = {'status': 'partial' if out else 'error', 'reason': str(e), 'packages_read': rank}; break
            for p in d if isinstance(d, list) else []:
                if not isinstance(p, dict) or rank >= total: continue
                rank += 1
                r = github_repo_of(str(p.get('repository_url') or '').strip().rstrip('/').removesuffix('.git'))
                if not r: skipped += 1; continue
                if r.lower() in seen: continue
                seen.add(r.lower()); out.append((r, rank, meta(p.get('name'))))
            if not isinstance(d, list) or len(d) < size: break
        self.status.setdefault('universe', {'status': 'ok'})
        self.status['universe'].update(ecosystem=ecosystem, packages=rank, repositories=len(out), packages_without_github_repository=skipped,
                                       sort=IMPL['universe_sort'], as_of='now', source='packages.ecosyste.ms (CC BY-SA 4.0, attribution: ecosyste.ms)')
        return out

    def _sourcegraph(self, key, alts, language, path, repos=None):
        q = 'patterntype:literal ' + _content(alts) + (' lang:' + language if language else '')
        if IMPL['excluded_paths']: q += ' -file:' + IMPL['excluded_paths']
        if path: q += ' file:' + re.escape(path)
        if repos: q += ' repo:^' + re.escape(urlsplit(GH['web']).hostname) + '/(' + '|'.join(re.escape(r) for r in repos) + ')$'
        q += f" count:{int(IMPL['universe_count' if repos else 'global_count'])} timeout:{int(IMPL['sourcegraph_timeout_s'])}s"
        try: s = self.cs._sourcegraph_get('https://sourcegraph.com/.api/search/stream?' + urlencode({'q': q, 'v': 'V3'})).decode('utf-8', 'replace')
        except (ValueError, RuntimeError) as e:
            self.status[key] = {'status': {'rate_limited': 'rate_limited', 'bot_challenge': 'blocked'}.get(str(e), 'error'), 'reason': str(e)}; return []
        complete = 'event: done' in s and 'event: error' not in s
        hits, full = [], False
        pmax, per, hmax = int(IMPL['path_max_chars']), int(IMPL['matches_per_file_max']), int(IMPL['hits_max'])
        for block in (b for b in s.split('\n\n') if b.startswith('event: matches')):
            if full: break
            try: items = json.loads('\n'.join(x[6:] for x in block.splitlines() if x.startswith('data: ')))
            except ValueError: continue
            for h in items if isinstance(items, list) else []:
                if not isinstance(h, dict) or h.get('type') != 'content' or not str(h.get('repository') or '').startswith(urlsplit(GH['web']).hostname + '/'): continue
                repo = h['repository'].split('/', 1)[1]
                if not re.fullmatch(GH_REPO, repo) or len(str(h.get('path') or '')) > pmax or not path_ok(str(h.get('path') or '')): continue
                ms = h.get('lineMatches') if isinstance(h.get('lineMatches'), list) else []
                for m in ms[:per]:                                       # bounds applied before any hit (and its URL) is built
                    if len(hits) >= hmax: full = True; break
                    if isinstance(m, dict) and isinstance(m.get('lineNumber'), int):
                        x = hit(repo, h['path'], m['lineNumber'] + 1, h.get('commit'), str(m.get('line') or ''))
                        x.update(stars=h.get('repoStars') if isinstance(h.get('repoStars'), int) else None, found_by=key)
                        hits.append(x)
                if full: break
        self.status[key] = {'status': 'truncated' if full else 'ok' if complete else 'incomplete', 'matches': len(hits), 'query': q,
                            **({'note': f'stopped at implementations.hits_max ({hmax}) hits'} if full else {})}
        return hits

    def _github(self, alts, language, path):
        token = None
        try: token = read_token()
        except ValueError: pass
        if not token:
            self.status['github'] = {'status': 'skipped', 'reason': 'credential_missing', 'note': GITHUB_CODE_SEARCH_KEYLESS}; return []
        hits, ex = [], re.compile(IMPL['excluded_paths']) if IMPL['excluded_paths'] else None
        for a in alts:
            try: r = self.cs.search(a, 'github', language=language, path=path, limit=int(IMPL['github_per_page']))
            except (ValueError, RuntimeError) as e: self.status['github'] = {'status': 'error', 'reason': str(e)}; break
            for h in r if isinstance(r, list) else []:
                if ex and ex.search(h['path']): continue
                hits.append(dict(h, stars=None, found_by='github'))
        self.status.setdefault('github', {'status': 'ok', 'matches': len(hits)})
        return hits

    def _groups(self, hits, universe):
        """Hits -> {repo key: group}: files (path -> lines, snippets, commit), stars, found_by, universe rank; vendored hits kept apart."""
        vend = re.compile(IMPL['vendored_paths']) if IMPL['vendored_paths'] else None
        rank = {r.lower(): (i, k, p) for i, (r, k, p) in enumerate(universe)}
        G = {}
        for h in hits:
            k = h['repo'].lower()
            g = G.setdefault(k, {'repo': h['repo'], 'stars': None, 'found_by': [], 'files': {}, 'universe': rank.get(k)})
            if h.get('stars') is not None: g['stars'] = max(g['stars'] or 0, h['stars'])
            if h['found_by'] not in g['found_by']: g['found_by'].append(h['found_by'])
            f = g['files'].setdefault(h['path'], {'path': h['path'], 'lines': [], 'snippets': [], 'commit': None, 'vendored': None})
            ms = list(vend.finditer(h['path'])) if vend else []
            if ms: f['vendored'] = h['path'][ms[-1].end():].split('/')[0] or None      # innermost copy: site-packages/pip/_vendor/urllib3 -> urllib3
            if h.get('revision') and f['commit'] and h['revision'] != f['commit']:
                f['other_revisions'] = f.get('other_revisions', 0) + 1; continue   # lines of two revisions are never merged under one commit
            if h.get('revision'): f['commit'] = h['revision']
            if h.get('line') and h['line'] not in f['lines']: f['lines'].append(h['line']); f['snippets'].append(h.get('snippet') or '')
        return G

    @staticmethod
    def _signature(f):
        return hashlib.sha256((f['path'].rsplit('/', 1)[-1] + '\0' + '\n'.join(sorted({_norm(s) for s in f['snippets']}))).encode()).hexdigest()

    def _copies(self, G, order):
        """Marks copies (in ranking order: the first holder of a content is the original): repositories whose matching files are all vendored
        (attributed to the upstream repository of that name when listed), and repositories whose non-vendored matching files all have the
        signature of a file of a better ranked repository."""
        seen = {}
        by_name = {}
        for k in order: by_name.setdefault(G[k]['repo'].split('/')[1].lower(), k)
        for k in order:
            g = G[k]; own = [f for f in g['files'].values() if not f['vendored']]
            if not own:
                up = sorted({f['vendored'] for f in g['files'].values() if f['vendored']})
                src = next((by_name[u.lower()] for u in up if u.lower() in by_name and by_name[u.lower()] != k), None)
                g['copy'] = {'kind': 'vendored', 'upstream_name': up, 'of': G[src]['repo'] if src else None,
                             'paths': sorted(g['files'])[:int(IMPL['hits_per_repo'])]}
                continue
            sigs = {self._signature(f) for f in own if f['snippets']}
            src = {seen[x] for x in sigs if x in seen}
            if sigs and all(x in seen for x in sigs) and len(src) == 1:
                g['copy'] = {'kind': 'same_content', 'of': G[src.pop()]['repo'], 'paths': sorted(f['path'] for f in own)[:int(IMPL['hits_per_repo'])]}
                continue
            for x in sigs: seen.setdefault(x, k)

    def _best(self, g):
        own = [f for f in g['files'].values() if not f['vendored']] or list(g['files'].values())
        return sorted(own, key=lambda f: (-len(f['lines']), len(f['path']), f['path']))[0]

    def _relocate(self, repo, sha, path, alts):
        """Lines of the file at the commit that contain one of the literals (case-insensitive), from the raw file (no API request)."""
        text = self.gh.file(repo, sha, path)['text'].split('\n')
        low = [a.lower() for a in alts]
        return [(i + 1, l[:400]) for i, l in enumerate(text) if any(a in l.lower() for a in low)]

    def _pin(self, g, f, alts, B):
        """Dates the cited commit through GitHubRepo.barrier; an indexed commit refused (after T, other branch) or a GitHub-only hit (no
        commit) is replaced by the last commit of the default branch before T. In both cases the lines and snippets served are those of the
        file read at the dated commit (Codex review 2026-10-31, item 3: the provider's text is never certified); a dated indexed commit
        whose file holds none of the literals is treated as refused."""
        repo = g['repo']
        if f['commit']:
            try:
                r = self.gh.resolve(repo, f['commit']); why = self.gh.barrier(repo, r, B, self.extra)
                if not why:
                    try: found = self._relocate(repo, r['sha'], f['path'], alts)
                    except ValueError as e:
                        if str(e) == 'rate_limited': raise
                        found, why = None, f'file not read at the indexed commit ({e})'
                    if found:
                        f['lines'], f['snippets'] = [x[0] for x in found], [x[1] for x in found]
                        return dict(sha=r['sha'], date=r['date'], status='indexed commit dated before T', backdate_check=r.get('backdate_check'))
                    why = why or 'the file at the indexed commit holds none of the literals (provider text not found)'
                first = why
            except ValueError as e:
                if str(e) == 'rate_limited': raise
                first = str(e)
        else: first = 'no commit given by the provider'
        try: h, why = self.gh.head_gated(repo, B, self.extra)
        except ValueError as e:
            if str(e) == 'rate_limited': raise
            return {'refusal': f'{first}; repository not resolved on GitHub ({e})'}
        if why: return {'refusal': first + '; ' + why}
        try: found = self._relocate(repo, h['sha'], f['path'], alts)
        except ValueError as e: return {'refusal': f"{first}; at the last commit before T ({h['sha'][:12]}): {e}"}
        if not found: return {'refusal': f"{first}; at the last commit before T ({h['sha'][:12]}) the file no longer matches"}
        f['lines'], f['snippets'] = [x[0] for x in found], [x[1] for x in found]
        return dict(sha=h['sha'], date=h['date'], status='last commit of the default branch before T (indexed commit: ' + first + ')',
                    backdate_check=h.get('backdate_check'))

    def find(self, arg, B, language=None, ecosystem=None, path=None, n=20):
        alts = _alternatives(arg)
        refuse(language is not None and not re.fullmatch(r'[A-Za-z0-9_.+#-]{1,40}', language), 'filter_invalid')
        refuse(path is not None and not re.fullmatch(r'[A-Za-z0-9_.+/#-]{1,160}', path), 'filter_invalid')
        if not ecosystem and language: ecosystem = IMPL['language_ecosystems'].get(language.lower())
        uni = self.universe(ecosystem) if ecosystem else []
        hits = self._sourcegraph('sourcegraph_universe', alts, language, path, [r for r, _, _ in uni]) if uni else []
        hits += self._sourcegraph('sourcegraph_global', alts, language, path)
        hits += self._github(alts, language, path)
        G = self._groups(hits, uni)
        order = sorted(G, key=lambda k: (0, G[k]['universe'][0]) if G[k]['universe'] else (1, -(G[k]['stars'] or -1), k))
        self._copies(G, order)
        distinct = [k for k in order if 'copy' not in G[k]]
        try: tok = bool(read_token())
        except ValueError: tok = False
        pins = int(IMPL['pinned_repos_with_token' if tok else 'pinned_repos'])
        out, stopped = [], None
        queue, served_max = list(distinct), max(1, min(int(n), int(IMPL['repos_served_max'])))
        while queue and len(out) < served_max:
            i, k = len(out), queue.pop(0)
            g = G[k]; f = self._best(g)
            x = {'rank': i + 1, 'repo': g['repo'], 'found_by': g['found_by'],
                 'popularity': {'stars': g['stars'], 'ecosystem_rank': g['universe'][1] if g['universe'] else None,
                                'package': g['universe'][2] if g['universe'] else None, 'as_of': 'now'},
                 'path': f['path'], 'files_matching': len(g['files']), 'copies': [G[c]['repo'] for c in order if G[c].get('copy', {}).get('of') == g['repo']]}
            pin = None
            if i < pins and not stopped:
                try: pin = self._pin(g, f, alts, B)
                except ValueError as e:
                    if str(e) != 'rate_limited': raise
                    stopped = 'GitHub API quota exhausted: the next repositories keep their indexed commit, undated'
                except RuntimeError as e: stopped = f'GitHub not reachable ({e})'
            if pin and 'refusal' in pin:
                x.update(refusal=pin['refusal']); out.append(x)
                back = [c for c in order if G[c].get('copy', {}).get('kind') == 'same_content' and G[c]['copy']['of'] == g['repo']]
                for c in back:                                           # a copy of a refused repository is no longer shown to be a copy:
                    G[c]['restored'] = G[c].pop('copy')                  # it comes back as a candidate, in ranking order (Codex review, item 11)
                pos = {c: j for j, c in enumerate(order)}
                queue = sorted(queue + back, key=pos.get)
                x['copies'] = [c for c in x['copies'] if c not in {G[b]['repo'] for b in back}]
                continue
            if G[k].get('restored'): x['restored'] = f"listed first as a same-content copy of {G[k]['restored']['of']}, which was refused at dating"
            sha = pin['sha'] if pin else f['commit']
            lines = sorted(f['lines'])
            x['lines'] = lines[:int(IMPL['lines_served'])]
            x['snippets'] = [s[:400] for _, s in sorted(zip(f['lines'], f['snippets']))][:int(IMPL['lines_served'])]
            if pin and sha and re.fullmatch(r'[0-9a-f]{40}', sha):
                span = f':{lines[0]}-{lines[-1]}' if lines else ''
                x.update(id=f"repo:{g['repo']}/{f['path']}@{sha}", cite=f"repo:{g['repo']}/{f['path']}{span}@{sha}",
                         permanent_url=GH['web'] + g['repo'] + '/blob/' + sha + '/' + quote(f['path'], safe='/') + (f'#L{lines[0]}' if lines else ''))
            elif sha and re.fullmatch(r'[0-9a-f]{40}', sha):              # undated: no citation form (Codex review 2026-10-31, item 4)
                x.update(id=None, index_commit=sha, note=f"undated: date it with repo-file {g['repo']}/{f['path']}@{sha} (or repo-info) before citing it under T")
            else: x['id'] = None; x['note'] = 'no commit known: read it with repo-head then repo-file'
            if pin: x.update(date=pin['date'], dating=pin['status'], **({'backdate_check': pin['backdate_check']} if pin.get('backdate_check') else {}))
            else: x['dating'] = 'absent (live index commit, not dated, snippets from the search index: check it with repo-info ' + g['repo'] + '@<sha> or repo-file before citing it under T)'
            out.append(x)
        copies = [{'repo': G[k]['repo'], **G[k]['copy']} for k in order if 'copy' in G[k]]
        self.extra['implementations'] = {'alternatives': alts, 'language': language, 'ecosystem': ecosystem, 'providers': self.status,
                                         'repositories_matching': len(G), 'distinct': len(distinct), 'served': len(out), 'pinned_max': pins,
                                         'copies_removed': copies[:int(IMPL['copies_served'])], 'copies_count': len(copies),
                                         **({'github_stopped': stopped} if stopped else {}),
                                         'ranking': 'ecosystem universe first (rank by ' + IMPL['universe_sort'] + ', observed now), then stars (observed now)',
                                         'caution': 'a match is not an implementation: read the cited file (repo-file) before any claim'}
        return out
