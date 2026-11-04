#!/usr/bin/env python3
"""Optional PISTE broker (KEYS.md "PISTE broker"): keeps the PISTE pair and the bearer token away from the process that runs the research.

Run it under ANOTHER user than the run (a system user with no shell and a private home); it reads PISTE_CLIENT_ID and PISTE_CLIENT_SECRET by
the skill's key rule (environment, else ~/.config/vp/piste_client_id.key and piste_client_secret.key of its own home), keeps the token in
memory only, and listens on a Unix socket. The gateway uses it when the environment variable named by config.json piste_broker.env (default
VP_PISTE_BROKER) holds the socket path: it then never reads the pair nor writes <state>/piste-token.json.

    python3 -I piste_broker.py --socket /run/vp-piste/piste.sock --allow-uid 1000 [--allow-uid ...] [--config config.json]

Protocol: one JSON line per connection {"method": "GET"|"POST", "url": "<https URL>", "body": "<JSON text>"|null}, one JSON line back:
{"status": <HTTP status>, "body": "<base64>"} or {"error": "not_configured"|"key_invalid"|"refused:<why>"|"transport_error:<type>"|...}.
Only the method + URL pairs of config.json piste_broker.routes are forwarded (GET: query free, no body; POST: no query, body a JSON object,
bounded); the token goes only to the API host, the pair only to the OAuth host (form body), HTTPS only, no redirect followed. A 401 of the
API gets one fresh token, then the 401 is returned. The answer never carries the pair nor the token. A peer whose uid is not allowed
(SO_PEERCRED) is closed without an answer. Standard library only; the file is self-contained (it may be installed alone with config.json)."""
import argparse
import base64
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
import urllib.error, urllib.parse, urllib.request

UA = {'User-Agent': 'VanishingPoint-piste-broker/1'}
KEYS = ('PISTE_CLIENT_ID', 'PISTE_CLIENT_SECRET')
LOG = sys.stderr                                # one line per request: time and status or error, never a URL nor a value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):   # refused before any second request
        raise urllib.error.URLError('redirect_refused')


def load_config(path):
    c = json.loads(pathlib.Path(path).read_text(encoding='utf-8'))['piste_broker']
    c['route_set'] = {(r['method'].upper(), r['url']) for r in c['routes']}
    return c


def key(name):
    """Same rule as the skill (code_sources.key): environment variable, else ~/.config/vp/<name in lower case>.key; None when absent."""
    v = os.environ.get(name)
    if v and v.strip(): return v.strip()
    try: v = (pathlib.Path.home() / '.config' / 'vp' / (name.lower() + '.key')).read_text().strip()
    except OSError: return None
    return v or None


class Refused(Exception):
    pass


def check(req, cfg):
    """Validated (method, url, body bytes or None) of a client request, else Refused (nothing is sent upstream)."""
    if not isinstance(req, dict): raise Refused('request')
    m, url, body = str(req.get('method') or '').upper(), req.get('url'), req.get('body')
    if not isinstance(url, str): raise Refused('url')
    u = urllib.parse.urlsplit(url)
    if u.username or u.password or u.fragment or u.port not in (None, 443): raise Refused('url')
    if (m, f'{u.scheme}://{u.hostname}{u.path}') not in cfg['route_set']: raise Refused('route')
    if m == 'GET':
        if body is not None: raise Refused('body')
        return m, url, None
    if u.query or not isinstance(body, str): raise Refused('body')
    try: ok = isinstance(json.loads(body), dict)
    except ValueError: ok = False
    if not ok: raise Refused('body')
    return m, url, body.encode()


class Upstream:
    """Token in memory, paced and serialised upstream calls (one lock: also the pace per host)."""
    def __init__(self, cfg, opener=None, credentials=None):
        self.cfg, self.lock, self.last, self.tok = cfg, threading.Lock(), {}, None
        self.opener = opener or urllib.request.build_opener(_NoRedirect())
        self.credentials = credentials or (lambda: tuple(key(k) for k in KEYS))
        self.api_host = urllib.parse.urlsplit(next(iter(cfg['route_set']))[1]).hostname
        self.oauth_host = urllib.parse.urlsplit(cfg['oauth']).hostname

    def http(self, method, url, data, headers):
        h = urllib.parse.urlsplit(url).hostname
        wait = self.last.get(h, 0) + float(self.cfg['intervals'].get(h, 0)) - time.time()
        if wait > 0: time.sleep(wait)
        self.last[h] = time.time()
        req = urllib.request.Request(url, data=data, headers=dict(UA, **headers), method=method)
        try:
            with self.opener.open(req, timeout=self.cfg['upstream_timeout_s']) as r: st, b = r.status, r.read(self.cfg['max_answer_bytes'] + 1)
        except urllib.error.HTTPError as e:
            st = e.code
            try: b = e.read(65536)
            except Exception: b = b''
        except Exception as e: return None, 'redirect_refused' if 'redirect_refused' in str(e) else 'transport_error:' + type(e).__name__
        if len(b) > self.cfg['max_answer_bytes']: return None, 'answer_too_large'
        return (st, b), None

    def token(self, force):
        if not force and self.tok and self.tok[1] > time.time() + self.cfg['token_margin_s']: return self.tok[0], None
        self.tok = None
        ci, cs = self.credentials()
        if not (ci and cs): return None, 'not_configured'
        if not all(re.fullmatch(r'[\x21-\x7e]{4,}', x) for x in (ci, cs)): return None, 'credential_invalid'
        form = urllib.parse.urlencode({'grant_type': 'client_credentials', 'client_id': ci, 'client_secret': cs, 'scope': 'openid'}).encode()
        r, err = self.http('POST', self.cfg['oauth'], form, {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'})
        if err: return None, err
        st, b = r
        if st in (400, 401): return None, 'key_invalid'
        if st == 429: return None, 'rate_limited'
        if st != 200: return None, f'oauth_http_{st}'
        try: j = json.loads(b); t = str(j['access_token']); ttl = int(j.get('expires_in') or 3600)
        except (ValueError, KeyError, TypeError): return None, 'oauth_unreadable'
        if not re.fullmatch(r'[\x21-\x7e]{8,}', t): return None, 'oauth_unreadable'
        self.tok = (t, time.time() + ttl)
        return t, None

    def call(self, method, url, data):
        """-> {'status', 'body'} or {'error'}; never the token nor the pair."""
        with self.lock:
            for attempt in (0, 1):
                t, err = self.token(force=attempt > 0)
                if err: return {'error': err}
                h = {'Authorization': 'Bearer ' + t, 'Accept': 'application/json', **({'Content-Type': 'application/json'} if data else {})}
                r, err = self.http(method, url, data, h)
                if err: return {'error': err}
                if r[0] != 401: break
            return {'status': r[0], 'body': base64.b64encode(r[1]).decode('ascii')}


def peer_uid(sock):
    try: return struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))[1]
    except (OSError, AttributeError): return None


def make_handler(cfg, upstream, allow):
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            if peer_uid(self.connection) not in allow: return
            self.connection.settimeout(cfg['client_timeout_s'])
            try: line = self.rfile.readline(cfg['max_request_bytes'] + 1)
            except OSError: return
            try:
                if len(line) > cfg['max_request_bytes'] or not line.endswith(b'\n'): raise Refused('size')
                try: req = json.loads(line)
                except ValueError: raise Refused('json') from None
                ans = upstream.call(*check(req, cfg))
            except Refused as e: ans = {'error': f'refused:{e}'}
            try: self.wfile.write(json.dumps(ans).encode() + b'\n')
            except OSError: pass
            log = ans.get('error') or ans.get('status')
            print(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {log}", file=LOG, flush=True)
    return Handler


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def serve(path, cfg, allow, upstream=None):
    """Bound server (not started); the socket is world-connectable (0666) and filtered by peer uid; its directory decides who can reach it."""
    path = pathlib.Path(path)
    if path.is_socket(): path.unlink()
    srv = Server(str(path), make_handler(cfg, upstream or Upstream(cfg), set(allow)))
    os.chmod(path, 0o666)
    return srv


def main(argv=None):
    a = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    a.add_argument('--socket', required=True)
    a.add_argument('--allow-uid', type=int, action='append', required=True, help='uid allowed to connect (repeat)')
    a.add_argument('--config', default=str(pathlib.Path(__file__).resolve().parent / 'config.json'))
    o = a.parse_args(argv)
    cfg = load_config(o.config)
    os.umask(0o077)
    srv = serve(o.socket, cfg, o.allow_uid)
    print('piste broker listening; pair ' + ('present' if all(key(k) for k in KEYS) else 'absent (answers not_configured)'), file=sys.stderr, flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
