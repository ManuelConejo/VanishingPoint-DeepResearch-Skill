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
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode, urlsplit

CFG = json.loads((pathlib.Path(__file__).resolve().parent / 'config.json').read_text())
INTERVAL = CFG['code_intervals']
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


def refuse(condition, code):
    """Typed refusal: every adapter error is a short ValueError code, never a message built from data."""
    if condition:
        raise ValueError(code)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # refused before any second request
        raise ValueError('redirect_refused')


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
        with self.opener.open(urllib.request.Request(url, data=body, headers=headers), timeout=30) as r:
            return r.status, r.read(MAX_BYTES + 1)

    def _record(self, rec):
        self.receipts.append(rec)
        if self.cache_dir:
            with open(self.cache_dir / 'requests.jsonl', 'a') as f:
                f.write(json.dumps(rec) + '\n')

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
            self._record(dict(rec, failure=code, seconds=round(time.time() - t0, 3)))
        if code:
            raise ValueError(code)  # raised outside the except block: no __context__ that could carry a header value
        rec['seconds'] = round(time.time() - t0, 3)
        if len(data) > MAX_BYTES:  # the receipt is written for this call too
            self._record(dict(rec, status=status, bytes=len(data), failure='response_too_large'))
            raise ValueError('response_too_large')
        self._record(dict(rec, status=status, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
        if raw:
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
    repo:/language:/path:), never words of the literal pattern (banc code 2026-10-31: 14/22 calls at 0 result with repo: inside the pattern)."""
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


def parse_sourcegraph(sse):
    out = []
    for block in (b for b in sse.split('\n\n') if b.startswith('event: matches')):
        for h in json.loads('\n'.join(x[6:] for x in block.splitlines() if x.startswith('data: '))):
            if h.get('type') == 'content':
                out += [hit(h['repository'].removeprefix('github.com/'), h['path'], m['lineNumber'] + 1, h.get('commit'), m['line'])
                        for m in h.get('lineMatches', [])]
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
            return parse_sourcegraph(s)[:limit]
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
    def __init__(self, client): self.c = client

    def search(self, arxiv, limit=5):
        arxiv = re.sub(r'(?i)^arxiv:\s*', '', str(arxiv).strip())          # the identity rule writes arxiv:<id>; the bare id is accepted too
        refuse(not re.fullmatch(r'\d{4}\.\d{4,5}(?:v\d+)?', arxiv), 'arxiv')
        arxiv = re.sub(r'v\d+$', '', arxiv)
        d = self.c.json('https://huggingface.co/api/papers/' + arxiv)
        p = d.get('paper', d)
        x = dict(arxiv=arxiv, date=p.get('publishedAt'), models=[], datasets=[], spaces=[], repos=[dict(
            url=p['githubRepo'], status='official_declared_hf', stars=p.get('githubStars'), date=p.get('publishedAt'))] if p.get('githubRepo') else [])
        for kind, k in (('models', 'models'), ('datasets', 'datasets'), ('spaces', 'spaces')):
            items = self.c.json('https://huggingface.co/api/' + kind + '?' + urlencode({'filter': 'arxiv:' + arxiv, 'limit': limit, 'full': 'true'}))
            x[k] = [dict(id=i.get('id'), url='https://huggingface.co/' + ('' if kind == 'models' else kind + '/') + i['id'], stars=i.get('likes'),
                         date=i.get('lastModified'), status='community_unverified') for i in items]
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
        try:
            if tok:
                try: d = self.c.json(url, tok)
                except ValueError as e:
                    if str(e) != 'provider_error:HTTP401': raise
                    mark_invalid(self.c.cache_dir, 'VP_GITHUB_TOKEN'); self.extra['key_invalid_github'] = 'VP_GITHUB_TOKEN rejected (401): anonymous retry'
                    d = self.c.json(url)
            else:
                self.extra.setdefault('github_token', f"absent: anonymous ({GH['anonymous_requests_per_hour']} requests/h)")
                d = self.c.json(url)
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
        return dict(sha=full, date=(c.get('committer') or {}).get('date'), author_date=(c.get('author') or {}).get('date'))

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

    def head_before(self, repo, T):
        """Last commit of the default branch dated before T (datetime.date of the question): GET /commits?sha=<default branch>&until=<T>
        (github_repo.head_candidates per page, newest first), the first whose committer date is before T, then resolved on the repository
        (resolve: /commits/<sha> and /compare) so that gate() decides as for any other commit. None when that page holds none."""
        br = self.info(repo).get('default_branch')
        refuse(not br, 'default_branch')
        d = self._api('repos/' + self.check(repo) + '/commits?' + urlencode({'sha': br, 'until': T.isoformat() + 'T00:00:00Z', 'per_page': int(GH['head_candidates'])}))
        for c in d if isinstance(d, list) else []:
            sha = str((c or {}).get('sha') or '') if isinstance(c, dict) else ''
            date = str(((c.get('commit') or {}).get('committer') or {}).get('date') or '') if sha else ''
            if re.fullmatch(r'[0-9a-f]{40}', sha) and re.match(r'\d{4}-\d{2}-\d{2}', date) and date[:10] < T.isoformat():
                return self.resolve(repo, sha)
        return None

    def tree(self, repo, sha, prefix=''):
        """File paths of the commit (GET /git/trees/<sha>?recursive=1): blobs under `prefix`, repository-relative paths only (path_ok),
        at most github_repo.tree_paths_served; truncated when GitHub cut its own list or the cap was reached."""
        refuse(not re.fullmatch(r'[0-9a-f]{40}', sha or ''), 'sha')
        refuse(prefix and not path_ok(prefix.rstrip('/')), 'reference')
        d = self._api('repos/' + self.check(repo) + '/git/trees/' + sha + '?' + urlencode({'recursive': 1}))
        pre = prefix.rstrip('/') + '/' if prefix else ''
        paths = [e['path'] for e in (d.get('tree') or []) if isinstance(e, dict) and e.get('type') == 'blob' and isinstance(e.get('path'), str)
                 and path_ok(e['path']) and len(e['path']) <= 300 and e['path'].startswith(pre)]
        cap = int(GH['tree_paths_served'])
        return dict(paths=paths[:cap], count=len(paths), truncated=bool(d.get('truncated')) or len(paths) > cap)

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
        url = GH['raw'] + self.check(repo) + '/' + sha + '/' + quote(path, safe='/')
        if url not in self.memo:
            try: self.memo[url] = self.c.get(url)
            except ValueError as e:
                refuse(str(e) == 'provider_error:HTTP404', 'file_not_found')
                raise
        data = self.memo[url]
        refuse(b'\0' in data, 'binary')
        return dict(text=data.decode('utf-8', 'replace'), bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                    permanent_url=GH['web'] + repo + '/blob/' + sha + '/' + quote(path, safe='/'))

    def file_at(self, repo, sha, path):
        """code-file / repo-file: the commit resolved on the named repository (dated, membership), then the whole file at its full SHA."""
        r = self.resolve(repo, sha)
        f = self.file(repo, r['sha'], path)
        return dict(f, id=f"repo:{repo}/{path}@{r['sha']}", repo=repo, path=path, sha=r['sha'], date=r['date'], origin=GH['web'] + repo,
                    membership=r['membership'], in_default_branch=r.get('in_default_branch'), repo_created_at=r.get('repo_created_at'),
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
USAGE_FORM = r'(' + '|'.join(USAGE_REGISTRY) + r'):(@?[A-Za-z0-9][\w.+:-]*(?:/[A-Za-z0-9][\w.+:-]*){0,3})'   # Maven group:artifact, npm @scope/name, Go paths
USAGE_FORM_MSG = 'expected form <' + '|'.join(USAGE_REGISTRY) + '>:<package>'


class Usage:
    """packages.ecosyste.ms (data CC BY-SA 4.0, keyless common pool): current usage counts and the releases published before a date.
    Never decides the barrier: returns the dates, gateway.code_usage applies it."""
    def __init__(self, client):
        self.c = client if USAGE_HOSTS <= client.hosts else CodeClient(hosts=client.hosts | USAGE_HOSTS, interval=client.interval, cache_dir=client.cache_dir, offline=client.offline)

    def lookup(self, system, package, before):
        refuse(system not in USAGE_REGISTRY, 'system')
        refuse(not re.fullmatch(r'\d{4}-\d{2}-\d{2}', before), 'date')
        refuse(not re.fullmatch(r'@?[A-Za-z0-9][\w.+:-]{0,200}(/[A-Za-z0-9][\w.+:-]{0,200}){0,3}', package) or any(s in ('.', '..') for s in package.split('/')), 'reference')
        p = quote(package, safe='')                                         # npm @scope/name, Go and Maven paths: one URL segment
        root = f'https://packages.ecosyste.ms/api/v1/registries/{USAGE_REGISTRY[system]}/packages/{p}'
        d = self.c.json(root)
        vs = self.c.json(root + '/versions?' + urlencode({'published_before': before, 'sort': 'published_at', 'order': 'desc', 'per_page': 100}))
        return dict(package=package, system=system, registry=USAGE_REGISTRY[system], purl=d.get('purl'), repository_url=d.get('repository_url'),
                    first_release_date=d.get('first_release_published_at'),
                    releases_before_T=[dict(number=v.get('number'), date=v.get('published_at')) for v in vs if isinstance(v, dict)],
                    dependent_packages_count=d.get('dependent_packages_count'), dependent_repos_count=d.get('dependent_repos_count'),
                    docker_dependents_count=d.get('docker_dependents_count'), downloads=d.get('downloads'), downloads_period=d.get('downloads_period'),
                    maintainers=[dict(login=m.get('login'), role=m.get('role')) for m in d.get('maintainers') or [] if isinstance(m, dict)],
                    licenses=d.get('licenses'), source='packages.ecosyste.ms (CC BY-SA 4.0, attribution: ecosyste.ms)')

    def repository(self, repo):
        """ecosyste.ms repository lookup by URL (config repo_metadata.ecosystems_repos; GitHub repository <owner>/<name>): licence, dates,
        archived, fork, stars, default branch, as observed now. Never decides the barrier (gateway.code_usage applies it to created_at)."""
        GitHubRepo.check(repo)
        d = self.c.json(RM['ecosystems_repos'] + '?' + urlencode({'url': GH['web'] + repo}))
        return dict(repository=repo_name(d.get('full_name'), repo), url=GH['web'] + repo, licence=meta(d.get('license')), created_at=meta(d.get('created_at')),
                    pushed_at=meta(d.get('pushed_at')), archived=d.get('archived'), fork=d.get('fork'), stars=d.get('stargazers_count'),
                    default_branch=meta(d.get('default_branch')), source='repos.ecosyste.ms (CC BY-SA 4.0, attribution: ecosyste.ms)')
