# SPDX-License-Identifier: Apache-2.0
"""Code sources of the VanishingPoint gateway. CodeClient = HTTPS only, closed host list, no redirect, 5 MB cap, per-host
interval from config.json, receipts without URL nor token; grep.app disabled; every key optional (GitHub token: VP_GITHUB_TOKEN
resolved by key('VP_GITHUB_TOKEN'), sent to api.github.com only, never logged; SWH_TOKEN sent to archive.softwareheritage.org only);
VP_OFFLINE=1 = no network. A key the provider rejects is remembered in <state>/keys-invalid.json (names only) and not sent again.
key(NAME) is the single key rule of the skill (KEYS.md), also used by gateway.py."""
import fcntl
import hashlib
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
HOSTS = frozenset(('api.github.com', 'sourcegraph.com', 'api.deps.dev', 'pypi.org', 'registry.npmjs.org', 'crates.io',
                   'huggingface.co', 'archive.softwareheritage.org', 'api.osv.dev'))
CRED_HOST = {'VP_GITHUB_TOKEN': 'api.github.com', 'SWH_TOKEN': 'archive.softwareheritage.org'}   # each credential goes to its own host only
TOKEN_PATH = None     # no token file fallback (kept as a module variable so tests can monkeypatch it harmlessly)
FALLBACK_DIRS = ()    # no fallback key directory (kept as a module variable so tests can monkeypatch it harmlessly)
MAX_BYTES, MAX_QUERY = 5_000_000, 512
UA = 'VanishingPoint/1 (research skill)'   # replaced below once key() is defined: VP_CONTACT follows the key rule (env, then ~/.config/vp/vp_contact.key)
SWH = 'https://archive.softwareheritage.org/'
ORIGIN = r'https://[A-Za-z0-9.-]+(?::\d+)?/\S*'   # an origin for Software Heritage: HTTPS, a plain host (no userinfo), a path
SWHID = r'swh:1:(cnt|dir|rev|rel|snp):[a-f0-9]{40}'


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
            code = 'rate_limited' if e.code in (429, 503) else f'provider_error:HTTP{e.code}'
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


def check_query(q, regex=False, language=None, repo=None):
    refuse(not isinstance(q, str) or not q.strip() or len(q) > MAX_QUERY or any(ord(c) < 32 for c in q), 'query_invalid')
    refuse(regex and (any(c in q for c in '()|{}') or re.search(r'\\[1-9]|\(\?', q)), 'regex_unbounded')  # bounded subset only
    refuse(any(x and not re.fullmatch(r'[A-Za-z0-9_.+/#-]{1,160}', x) for x in (language, repo)), 'filter_invalid')


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


class CodeSearch:
    def __init__(self, client): self.c = client

    def search(self, q, provider='sourcegraph', regex=False, language=None, repo=None, limit=10):
        check_query(q, regex, language, repo)
        refuse(not 1 <= limit <= 100, 'limit')
        refuse(provider == 'grep', 'provider_disabled')  # grep.app: 429 and anti-bot, live index, abandoned
        refuse(provider not in ('sourcegraph', 'github'), 'provider')
        if provider == 'sourcegraph':
            quoted = 'content:"' + q.replace('\\', '\\\\').replace('"', '\\"') + '"'   # a filter word inside q stays part of the pattern
            query = ('patterntype:regexp ' if regex else 'patterntype:literal ') + quoted + f' count:{limit} timeout:10s'
            query += (' lang:' + language if language else '') + (' repo:^github\\.com/' + re.escape(repo) + '$' if repo else '')
            s = self.c.get('https://sourcegraph.com/.api/search/stream?' + urlencode({'q': query, 'v': 'V3'})).decode()
            refuse('event: error' in s or 'event: done' not in s, 'sourcegraph_incomplete')
            return parse_sourcegraph(s)[:limit]
        refuse(regex, 'github_rest_regex_unsupported')
        token = read_token()
        if not token:
            return {'status': 'skipped', 'reason': 'credential_missing'}
        query = '"' + q.replace('"', '\\"') + '"' + (' language:' + language if language else '') + (' repo:' + repo if repo else '')
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

    def visit(self, origin):
        refuse(not re.fullmatch(ORIGIN, origin), 'origin')
        d = self._json(SWH + 'api/1/origin/' + quote(origin, safe='') + '/visit/latest/?require_snapshot=true')
        snp = 'swh:1:snp:' + d['snapshot'] if d.get('snapshot') else None
        return dict(origin=origin, swhid=snp, date_visited=d.get('date'), status=d.get('status'), permanent_url=SWH + (snp or ''))

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


# ---------------------------------------------------------------- package usage (ecosyste.ms), engine `usage` (plugins/code.md)
USAGE_HOSTS = frozenset(('packages.ecosyste.ms',))
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
