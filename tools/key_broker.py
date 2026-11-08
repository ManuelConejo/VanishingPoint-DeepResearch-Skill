#!/usr/bin/env python3
"""Optional key broker (KEYS.md "Key broker"): keeps every API key away from the process that runs the research.

Run it under ANOTHER user than the run (a system user with no shell); it alone reads the keys (environment variable NAME, else
<keys dir>/<name in lower case>.key; keys dir = --keys-dir, else $CREDENTIALS_DIRECTORY (systemd LoadCredential=), else ~/.config/vp),
re-read at every request, and listens on a Unix socket. When the environment variable named by config.json key_broker.env (default
VP_KEY_BROKER) holds the socket path, the run never reads a key: code_sources.key(NAME) answers a non-secret placeholder (PLACEHOLDER below)
for the keys the broker holds, and every request that carries a placeholder goes through the broker, which puts the real key in its place.

    python3 -I key_broker.py --socket /run/vp-keys/keys.sock --allow-uid 1000 [--allow-uid ...] [--config config.json] [--keys-dir DIR]

Routes (which key may go where, and how) are DERIVED, never written twice: the `key` block of every source (tools/sources/*.py, read as text
with ast, never imported nor executed: `vars`, `send` = query:<param> | bearer | header:<name>, `hosts`), plus one route per contradictor
provider of config.json contradictor.providers (`key`, https `url`: Bearer, POST to that path, GET to its check_url or <base>/models).
Names of key_broker.not_secret (VP_CONTACT) are not keys and get no route.

Protocol: one JSON line per connection, one JSON line back.
  {"op": "keys"} -> {"keys": [names with a route that the broker holds], "held": [every name held, PISTE pair included]}
  {"op": "fetch", "method": "GET"|"POST", "url": "<https URL>", "headers": {..}, "body": "<base64>"|null}
      -> {"status": <HTTP status>, "headers": {<key_broker.forward_headers>}, "body": "<base64>"} or {"error": "<code>"}
  a line without "op" = the PISTE broker protocol (tools/piste_broker.py), served on the same socket when key_broker.piste is true.
A fetch is forwarded only when: https, port 443, no userinfo nor fragment; at least one placeholder; every placeholder names a key with a
route whose hosts contain the EXACT host, and sits exactly where that route sends it (the whole value of the query parameter, the whole
`Authorization: Bearer` value, the whole value of the named header), nowhere else (path, other parameters, other headers, body); client
headers limited to key_broker.client_headers; GET only for source keys, POST only to a provider's chat path. No redirect is followed (the
3xx is returned with its Location); sizes and delays bounded by config.json key_broker. Answers and logs never carry a key: every form of it
(raw, URL-encoded) in the body or a forwarded header is replaced by MASK; errors are codes and exception type names. A peer whose uid is not
allowed (SO_PEERCRED) is closed without an answer. Standard library only; this file is also the client used by the run."""
import argparse
import ast
import base64
import email.message
import io
import json
import os
import pathlib
import re
import socket
import socketserver
import struct
import sys
import threading
import time
import urllib.error, urllib.parse, urllib.request, urllib.response

HERE = pathlib.Path(__file__).resolve().parent
UA = 'VanishingPoint-key-broker/1'
PLACEHOLDER = 'VPKB.{}.VPKB'                                    # never a secret: names the key the broker puts in its place
PH_RE = re.compile(r'VPKB\.([A-Z][A-Z0-9_]{0,63})\.VPKB')
MASK = b'[key withheld]'
LOG = sys.stderr                                                # one line per request: time, uid, op, names, host, status or error


def load_config(path=None):
    """The whole config.json (key_broker, contradictor.providers and piste_broker are read from it)."""
    return json.loads(pathlib.Path(path or HERE / 'config.json').read_text(encoding='utf-8'))


# ------------------------------------------------------------------------------------------------------------- routes

def source_specs(sources_dir):
    """[(file name, {'vars', 'send', 'hosts'})] of every `'key': {...}` block of tools/sources/*.py, read with ast (literal values only;
    a block whose vars, send or hosts are not literals, such as the PISTE pair, is skipped: it has its own broker protocol)."""
    out = []
    for f in sorted(pathlib.Path(sources_dir).glob('*.py')):
        try: tree = ast.parse(f.read_text(encoding='utf-8'), str(f))
        except (OSError, SyntaxError, ValueError): continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict): continue
            for k, v in zip(node.keys, node.values):
                if not (isinstance(k, ast.Constant) and k.value == 'key' and isinstance(v, ast.Dict)): continue
                spec = {}
                for kk, vv in zip(v.keys, v.values):
                    if isinstance(kk, ast.Constant) and kk.value in ('vars', 'send', 'hosts'):
                        try: spec[kk.value] = ast.literal_eval(vv)
                        except ValueError: pass
                if set(spec) == {'vars', 'send', 'hosts'}: out.append((f.name, spec))
    return out


def build_routes(cfg, sources_dir=None):
    """name -> {'send': 'query:<p>'|'bearer'|'header:<h>', 'hosts': {host}, 'post': {(host, path)}, 'get_paths': {(host, path)}|None}.
    get_paths None = any GET path on the hosts (source keys); provider keys: GET only to their check path, POST only to their chat path."""
    kb, routes = cfg['key_broker'], {}
    skip = set(kb['not_secret'])

    def add(name, send, hosts, post=(), get_paths=None):
        if name in skip or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}', name): return
        if not (send == 'bearer' or re.fullmatch(r'(query|header):[A-Za-z0-9_.-]+', send)): return
        if name not in routes: routes[name] = {'send': send, 'hosts': set(), 'post': set(), 'get_paths': get_paths}
        r = routes[name]
        if r['send'] != send: raise ValueError(f'{name}: two send modes ({r["send"]}, {send})')
        r['hosts'] |= {h.lower() for h in hosts}; r['post'] |= set(post)
        if r['get_paths'] is not get_paths: r['get_paths'] = None if get_paths is None or r['get_paths'] is None else r['get_paths'] | get_paths
    for _, s in source_specs(sources_dir or HERE / kb['sources_dir']):
        for name in s['vars']: add(name, s['send'], s['hosts'])
    for prov in (cfg.get('contradictor') or {}).get('providers', {}).values():
        name, url = prov.get('key'), prov.get('url') or ''
        u = urllib.parse.urlsplit(url)
        if not name or u.scheme != 'https' or not u.hostname: continue
        chk = urllib.parse.urlsplit(prov.get('check_url') or re.sub(r'/chat/completions/?$', '', url) + '/models')
        gets = {(chk.hostname, chk.path)} if chk.scheme == 'https' and chk.hostname else set()
        add(name, 'bearer', {u.hostname} | {h for h, _ in gets}, post={(u.hostname, u.path)}, get_paths=gets)
    return routes


# ------------------------------------------------------------------------------------------------------------- keys

def read_key(name, keys_dir=None):
    """The broker's own key rule: environment variable NAME, else <keys dir>/<name lower>.key; None when absent or empty."""
    v = os.environ.get(name)
    if v and v.strip(): return v.strip()
    d = pathlib.Path(keys_dir or os.environ.get('CREDENTIALS_DIRECTORY') or pathlib.Path.home() / '.config' / 'vp')
    try: v = (d / (name.lower() + '.key')).read_text().strip()
    except OSError: return None
    return v or None


def mask(data, secrets):
    """data (bytes) with every form of every secret (raw, URL-encoded, form-encoded) replaced by MASK."""
    for s in secrets:
        for form in sorted({s, urllib.parse.quote(s, safe=''), urllib.parse.quote_plus(s), urllib.parse.quote(s)}, key=len, reverse=True):
            if form: data = data.replace(form.encode(), MASK)
    return data


class Refused(Exception):
    pass


def _bounded_read(resp, max_bytes, deadline):
    out, n = [], 0
    rd = getattr(resp, 'read1', None) or resp.read
    while n <= max_bytes:
        if time.monotonic() > deadline: raise TimeoutError('deadline')
        b = rd(min(65536, max_bytes + 1 - n))
        if not b: break
        out.append(b); n += len(b)
    return b''.join(out)


def _with_deadline(fn, seconds):
    box = {}

    def run():
        try: box['v'] = fn()
        except BaseException as e: box['e'] = e                         # noqa: B902 (re-raised in the caller's thread)
    t = threading.Thread(target=run, daemon=True); t.start(); t.join(seconds)
    if t.is_alive(): raise TimeoutError('deadline')
    if 'e' in box: raise box['e']
    return box['v']


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):   # None: urllib raises the 3xx as an HTTPError, nothing is followed
        return None


class Broker:
    """Validates a fetch, puts the keys in, sends it once, masks the answer. keys(name) -> value or None (default read_key)."""
    def __init__(self, cfg, routes=None, opener=None, keys=None, keys_dir=None):
        self.cfg, self.kb = cfg, cfg['key_broker']
        self.routes = build_routes(cfg) if routes is None else routes
        self.opener = opener or urllib.request.build_opener(_NoRedirect())
        self.keys = keys or (lambda n: read_key(n, keys_dir))
        self.client_headers = {h.lower() for h in self.kb['client_headers']}
        self.forward = {h.lower(): h for h in self.kb['forward_headers']}
        self.min_chars = int(self.kb['min_key_chars'])

    def value(self, name):
        v = self.keys(name)
        if v is None: return None, 'not_configured'
        if not re.fullmatch(r'[\x21-\x7e]{%d,}' % self.min_chars, v): return None, 'credential_invalid'
        return v, None

    def held(self):
        return sorted(n for n in self.routes if self.value(n)[0])

    def plan(self, req):
        """(method, url, headers, body bytes or None, {name: placeholder location}) of a valid fetch, else Refused (nothing sent)."""
        if not isinstance(req, dict): raise Refused('request')
        m, url, hdrs, body = str(req.get('method') or '').upper(), req.get('url'), req.get('headers') or {}, req.get('body')
        if m not in ('GET', 'POST'): raise Refused('method')
        if not isinstance(url, str) or len(url) > int(self.kb['max_url_chars']) or any(ord(c) < 33 or ord(c) > 126 for c in url): raise Refused('url')
        u = urllib.parse.urlsplit(url)
        try: port = u.port
        except ValueError: raise Refused('url') from None
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.fragment or port not in (None, 443): raise Refused('url')
        host = u.hostname.lower()
        if not isinstance(hdrs, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in hdrs.items()): raise Refused('headers')
        if any(re.search(r'[\r\n\0]', k + v) for k, v in hdrs.items()): raise Refused('headers')
        if body is not None:
            if not isinstance(body, str): raise Refused('body')
            try: body = base64.b64decode(body, validate=True)
            except ValueError: raise Refused('body') from None
            if PH_RE.search(body.decode('latin-1')): raise Refused('placeholder_in_body')
        if m == 'GET' and body is not None: raise Refused('body')
        names = {}
        for seg in u.query.split('&') if u.query else ():               # a placeholder only as the whole value of its route's parameter
            k, _, v = seg.partition('=')
            if not PH_RE.search(seg): continue
            mm = PH_RE.fullmatch(v)
            if not mm or PH_RE.search(k) or mm.group(1) in names: raise Refused('placeholder_place')
            names[mm.group(1)] = ('query', k)
        if PH_RE.search(u.path) or PH_RE.search(u.netloc): raise Refused('placeholder_place')
        for k, v in hdrs.items():
            kl = k.lower()
            if not PH_RE.search(v):
                if kl not in self.client_headers: raise Refused('header')
                continue
            mm = re.fullmatch('Bearer ' + PH_RE.pattern, v) if kl == 'authorization' else PH_RE.fullmatch(v)
            if not mm or mm.group(1) in names: raise Refused('placeholder_place')
            names[mm.group(1)] = ('bearer', None) if kl == 'authorization' else ('header', kl)
        if not names: raise Refused('no_key')                           # never an open proxy
        for name, (where, what) in names.items():
            r = self.routes.get(name)
            if not r: raise Refused('no_route')
            if host not in r['hosts']: raise Refused('host')
            want = r['send'].lower()
            if not ((where == 'query' and r['send'] == 'query:' + what) or (where == 'bearer' and want == 'bearer')
                    or (where == 'header' and want == 'header:' + what)): raise Refused('placeholder_place')
            if m == 'POST' and (host, u.path) not in r['post']: raise Refused('method')
            if m == 'GET' and r['get_paths'] is not None and (host, u.path) not in r['get_paths']: raise Refused('path')
        return m, url, hdrs, body, names

    def fetch(self, req):
        """-> (answer dict: status, headers, body | error, {name: place}); never a key in the answer."""
        m, url, hdrs, body, names = self.plan(req)
        vals = {}
        for n in names:
            v, err = self.value(n)
            if err: return {'error': err}, names
            vals[n] = v
        u = urllib.parse.urlsplit(url)
        segs = []
        for seg in (u.query.split('&') if u.query else ()):
            k, _, v = seg.partition('=')
            mm = PH_RE.fullmatch(v)
            segs.append(k + '=' + urllib.parse.quote(vals[mm.group(1)], safe='') if mm else seg)
        real_url = urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, '&'.join(segs), ''))
        h = {'User-Agent': UA}
        for k, v in hdrs.items():
            mm = PH_RE.search(v)
            h[k] = v.replace(mm.group(0), vals[mm.group(1)]) if mm else v
        h['Accept-Encoding'] = 'identity'                               # a compressed answer could not be masked
        secrets = list(vals.values())
        total, cap = float(self.kb['upstream_total_timeout_s']), int(self.kb['max_answer_bytes'])
        deadline = time.monotonic() + total

        def go():
            rq = urllib.request.Request(real_url, data=body, headers=h, method=m)
            try:
                with self.opener.open(rq, timeout=float(self.kb['upstream_socket_timeout_s'])) as r:
                    return r.status, r.headers, _bounded_read(r, cap, deadline)
            except urllib.error.HTTPError as e:
                try: data = _bounded_read(e, cap, deadline)
                except Exception: data = b''                            # noqa: BLE001 (an unreadable error body is an empty one)
                return e.code, e.headers, data
        try: st, rh, data = _with_deadline(go, total)
        except TimeoutError: return {'error': 'timeout'}, names
        except Exception as e:                                          # noqa: BLE001 (typed by name only: no URL, no header, no key)
            return {'error': 'transport_error:' + type(e).__name__}, names
        if len(data) > cap: return {'error': 'answer_too_large'}, names
        if rh is not None and str(rh.get('Content-Encoding') or 'identity').strip().lower() != 'identity':
            return {'error': 'encoded_answer'}, names                   # never forwarded unmasked
        fh = {}
        for k, v in (rh.items() if rh is not None else ()):
            if k.lower() in self.forward and self.forward[k.lower()] not in fh:
                fh[self.forward[k.lower()]] = mask(str(v).encode('latin-1', 'replace'), secrets).decode('latin-1')[:int(self.kb['max_header_chars'])]
        return {'status': int(st), 'headers': fh, 'body': base64.b64encode(mask(data, secrets)).decode('ascii')}, names


def peer_uid(sock):
    try: return struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))[1]
    except (OSError, AttributeError): return None


def piste_route(cfg, keys):
    """(piste_broker module, its config, its Upstream) when key_broker.piste is true and piste_broker.py sits beside this file; else None.
    The PISTE pair is read by the same rule as the other keys (keys(name))."""
    if not cfg['key_broker'].get('piste') or 'piste_broker' not in cfg: return None
    sys.path.insert(0, str(HERE))
    try: import piste_broker as pb
    except ImportError: return None
    finally: sys.path.remove(str(HERE))
    pc = dict(cfg['piste_broker']); pc['route_set'] = {(r['method'].upper(), r['url']) for r in pc['routes']}
    return pb, pc, pb.Upstream(pc, credentials=lambda: tuple(keys(k) for k in pb.KEYS))


def make_handler(cfg, broker, allow, piste=None):
    kb = cfg['key_broker']; gate = threading.BoundedSemaphore(int(kb['max_concurrent']))

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            uid = peer_uid(self.connection)
            if uid not in allow: return
            self.connection.settimeout(float(kb['client_read_timeout_s']))
            try: line = self.rfile.readline(int(kb['max_request_bytes']) + 1)
            except OSError: return
            op, names, host = '-', {}, '-'
            if not gate.acquire(timeout=float(kb['client_read_timeout_s'])): ans = {'error': 'busy'}
            else:
                try:
                    if len(line) > int(kb['max_request_bytes']) or not line.endswith(b'\n'): raise Refused('size')
                    try: req = json.loads(line)
                    except ValueError: raise Refused('json') from None
                    if not isinstance(req, dict): raise Refused('request')
                    op = str(req.get('op') or 'piste')[:10]
                    if op == 'keys':
                        held = broker.held()
                        pair = bool(piste) and all(broker.value(k)[0] for k in piste[0].KEYS)
                        ans = {'keys': held, 'held': sorted(set(held) | (set(piste[0].KEYS) if pair else set()))}
                    elif op == 'fetch':
                        host = (urllib.parse.urlsplit(str(req.get('url') or '')).hostname or '-')[:80]
                        ans, names = broker.fetch(req)
                    elif op == 'piste' and piste:
                        host = 'piste'; ans = piste[2].call(*piste[0].check(req, piste[1]))
                    else: raise Refused('op')
                except (Refused, ValueError) as e: ans = {'error': f'refused:{e}' if isinstance(e, Refused) else 'refused:url'}
                except Exception as e: ans = {'error': 'internal:' + type(e).__name__}   # noqa: BLE001 (no traceback: it could quote a URL)
                finally: gate.release()
            try: self.wfile.write(json.dumps(ans).encode() + b'\n')
            except OSError: pass
            log = ans.get('error') or ans.get('status') or 'keys'
            print(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} uid={uid} op={op} keys={','.join(sorted(names)) or '-'} host={host} {log}",
                  file=LOG, flush=True)
    return Handler


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def handle_error(self, request, client_address):                    # one line, never a traceback (it could quote a URL)
        print(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} handler_error {type(sys.exc_info()[1]).__name__}", file=LOG, flush=True)


def serve(path, cfg, allow, broker=None, piste=None, keys_dir=None):
    """Bound server (not started); the socket is world-connectable (0666) and filtered by peer uid; its directory decides who can reach it.
    piste: None = from config (key_broker.piste), False = no PISTE route, or a (module, config, upstream) triple (tests)."""
    path = pathlib.Path(path)
    if path.is_socket(): path.unlink()
    broker = broker or Broker(cfg, keys_dir=keys_dir)
    if piste is None: piste = piste_route(cfg, broker.keys)
    srv = Server(str(path), make_handler(cfg, broker, set(allow), piste or None))
    os.chmod(path, 0o666)
    return srv


def main(argv=None):
    a = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    a.add_argument('--socket')
    a.add_argument('--allow-uid', type=int, action='append', help='uid allowed to connect (repeat)')
    a.add_argument('--config', default=str(HERE / 'config.json'))
    a.add_argument('--keys-dir', default=None, help='directory of <name lower>.key files (default $CREDENTIALS_DIRECTORY, else ~/.config/vp)')
    a.add_argument('--routes', action='store_true', help='print the derived routes (names, send mode, hosts, held or not; never a value) and exit')
    o = a.parse_args(argv)
    cfg = load_config(o.config)
    os.umask(0o077)
    b = Broker(cfg, keys_dir=o.keys_dir)
    if o.routes:
        for n, r in sorted(b.routes.items()):
            print(f"{n}: {r['send']} -> {', '.join(sorted(r['hosts']))}" + (f" (POST {', '.join(sorted(p for _, p in r['post']))})" if r['post'] else '')
                  + (' [held]' if b.value(n)[0] else ''))
        return 0
    if not (o.socket and o.allow_uid): a.error('--socket and --allow-uid are required')
    srv = serve(o.socket, cfg, o.allow_uid, broker=b)
    print(f'key broker listening; {len(b.held())} of {len(b.routes)} routed keys held', file=sys.stderr, flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    return 0


# ------------------------------------------------------------------------------------------------------------- client (the run's side)

_CFG = {}
_NAMES = {}                                                     # socket path -> (expiry monotonic, answer dict or None)


def ccfg():
    """key_broker block of the config.json beside this file (the run's own copy: env name, timeouts, names cache)."""
    if not _CFG: _CFG.update(load_config()['key_broker'])
    return _CFG


def socket_path():
    """The broker socket (environment variable key_broker.env), else None: then nothing changes for the run."""
    return os.environ.get(ccfg()['env'], '').strip() or None


def active(): return socket_path() is not None


def not_secret(name): return name in ccfg()['not_secret']


def placeholder(name): return PLACEHOLDER.format(name)


class BrokerError(OSError):
    """The broker refused or failed a request (a code only: refused:<why>, not_configured, transport_error:<type>, broker_unreachable...)."""


def _exchange(obj):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(float(ccfg()['client_timeout_s'])); s.connect(socket_path())
        s.sendall(json.dumps(obj).encode() + b'\n')
        buf, n, cap = [], 0, int(ccfg()['max_answer_bytes']) * 4 // 3 + 1_000_000
        while n <= cap:
            c = s.recv(1 << 16)
            if not c: break
            buf.append(c); n += len(c)
            if c.endswith(b'\n'): break
    raw = b''.join(buf)
    if not raw.endswith(b'\n'): raise BrokerError('broker_closed')
    return json.loads(raw)


def names(force=False):
    """{'keys': [...], 'held': [...]} as told by the broker (names only), cached key_broker.names_cache_s; None when unreachable."""
    path = socket_path()
    if not path: return None
    hit = _NAMES.get(path)
    if hit and not force and hit[0] > time.monotonic(): return hit[1]
    try:
        a = _exchange({'op': 'keys'})
        ans = {'keys': [str(x) for x in a.get('keys') or []], 'held': [str(x) for x in a.get('held') or []]} if isinstance(a, dict) and 'keys' in a else None
    except (OSError, ValueError): ans = None
    _NAMES[path] = (time.monotonic() + float(ccfg()['names_cache_s']), ans)
    return ans


def forget(): _NAMES.clear()


def client_key(name):
    """What code_sources.key(name) answers in broker mode: the placeholder when the broker holds a routed key of that name, else None.
    No file, no environment variable of a key is read."""
    n = names()
    return placeholder(name) if n and name in n['keys'] else None


def needs(url, headers=None):
    """True when the request carries a placeholder (and so must go through the broker)."""
    return active() and bool(PH_RE.search(str(url)) or any(PH_RE.search(str(v)) for v in dict(headers or {}).values()))


def request(method, url, headers=None, body=None):
    """(status, headers dict, body bytes) through the broker, or BrokerError(code)."""
    try: a = _exchange({'op': 'fetch', 'method': method, 'url': url, 'headers': dict(headers or {}),
                        'body': base64.b64encode(body).decode('ascii') if body is not None else None})
    except BrokerError: raise
    except (OSError, ValueError) as e: raise BrokerError('broker_unreachable:' + type(e).__name__) from None
    if not isinstance(a, dict) or 'status' not in a:
        raise BrokerError('key_broker:' + (str(a.get('error') or 'answer')[:120] if isinstance(a, dict) else 'answer'))
    try: return int(a['status']), dict(a.get('headers') or {}), base64.b64decode(a.get('body') or '')
    except (TypeError, ValueError): raise BrokerError('key_broker:answer') from None


def open_request(req):
    """urllib.request.Request -> a response like urlopen's (status, headers, read, read1), through the broker; an HTTP status >= 300 is
    raised as urllib.error.HTTPError carrying the masked body and the forwarded headers (Location of a refused redirect)."""
    st, h, data = request(req.get_method(), req.full_url, dict(req.header_items()), req.data)
    m = email.message.Message()
    for k, v in h.items(): m[k] = v
    if st >= 300: raise urllib.error.HTTPError(req.full_url, st, 'via key broker', m, io.BytesIO(data))
    return urllib.response.addinfourl(io.BytesIO(data), m, req.full_url, st)


if __name__ == '__main__':
    sys.exit(main())
