# SPDX-License-Identifier: Apache-2.0
"""PISTE engines (Judilibre, Legifrance; plugins/law.md sections 5-6): search-judilibre [--court] [--chamber] [--from] [--to],
search-legifrance [--fund code|loda|jorf], read judilibre:<id> | legi:LEGIARTI.../LEGITEXT... | jorf:JORFTEXT...
Credentials PISTE_CLIENT_ID + PISTE_CLIENT_SECRET (OAuth client credentials), else skipped with 0 request."""
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import code_sources as sc
import time
import urllib.error, urllib.parse, urllib.request
from sources._common import Barrier, ProviderError, STATE, UA, _before, head_tail, interval, key, law_ok, plain, window


# ---------------------------------------------------------------- PISTE engines (v0.4.7, plugins/law.md sections 5-6): judilibre, legifrance
# Not yet verified on the live service (no credentials at release). OAuth 2.0 client credentials (PISTE_CLIENT_ID + PISTE_CLIENT_SECRET, key()):
# the pair goes only to oauth.piste.gouv.fr (form body, never a URL), the bearer only to api.piste.gouv.fr; HTTPS only, no redirect followed,
# receipts in <state>/requests.jsonl without URL, body nor token; the token is cached in <state>/piste-token.json (0600) with its expiry.
# Without the pair: 0 request, {"status": "skipped", "reason": "not_configured"}. Rejected pair (token 400/401, or API 401 twice) -> key_invalid.
# Endpoints: Judilibre OpenAPI (github.com/Cour-de-cassation/judilibre-search, public/JUDILIBRE-public.json, v1.2.5): GET /search, GET /decision;
# Legifrance (DILA, "Exemples d'utilisation de l'API Legifrance" V3 2025-09-17, "Description des tris et filtres"): POST /search,
# /consult/getArticle, /consult/legiPart, /consult/jorf.
PISTE_OAUTH = 'https://oauth.piste.gouv.fr/api/oauth/token'
JUDILIBRE = 'https://api.piste.gouv.fr/cassation/judilibre/v1.0/'
LEGIFRANCE = 'https://api.piste.gouv.fr/dila/legifrance/lf-engine-app/'
PISTE_KEYS = ('PISTE_CLIENT_ID', 'PISTE_CLIENT_SECRET')
PISTE_HOST = {'credentials': 'oauth.piste.gouv.fr', 'bearer': 'api.piste.gouv.fr'}   # each secret to its own host only
PISTE_PREFIX = ('judilibre:', 'legi:', 'jorf:')
PISTE_TOKEN = 'piste-token.json'
PISTE_MAX = 20_000_000
_PISTE_OPENER = urllib.request.build_opener(sc._NoRedirect())               # a redirect is refused before any second request


class PisteSkip(Exception):
    """The PISTE engine is skipped (not_configured, key_invalid, credential_invalid, not_subscribed): a receipt, never "nothing found"."""
    def __init__(self, reason, detail): super().__init__(reason); self.reason, self.detail = reason, detail


def piste_skipped(e):
    return {'status': 'skipped', 'reason': e.reason, 'refusal': f'{e.reason}: {e.detail}', **({'requests': 0} if e.reason == 'not_configured' else {})}


def piste_http(url, data=None, headers=None, cred=None):
    """One HTTPS call to a PISTE host -> (status, bytes); a secret only to its host (cred), no redirect; receipt without URL nor token.
    Transport failures raise ProviderError outside the except block (no traceback context carrying a header)."""
    u = urllib.parse.urlsplit(url)
    if u.scheme != 'https' or u.port not in (None, 443) or u.username or u.password or u.hostname not in PISTE_HOST.values(): raise ValueError('host_not_declared')
    if cred and u.hostname != PISTE_HOST[cred]: raise ValueError('credential_host')
    STATE.mkdir(parents=True, exist_ok=True)
    with open(STATE / f'rate-{u.hostname}.lock', 'a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX); f.seek(0); wait = float(f.read() or 0) + interval(u.hostname) - time.time()
        if wait > 0: time.sleep(wait)
        f.seek(0); f.truncate(); f.write(str(time.time()))
    t0 = time.time(); rec = {'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t0)), 'host': u.hostname, 'path_sha256': hashlib.sha256(u.path.encode()).hexdigest()}
    status, body, fail = None, b'', None
    try:
        with _PISTE_OPENER.open(urllib.request.Request(url, data=data, headers=dict(UA, **(headers or {})), method='POST' if data is not None else 'GET'), timeout=40) as r:
            status, body = r.status, r.read(PISTE_MAX + 1)
    except urllib.error.HTTPError as e:
        status = e.code
        try: body = e.read(65536)
        except Exception: body = b''
    except Exception as e: fail = 'redirect_refused' if str(e) == 'redirect_refused' else 'transport_error:' + type(e).__name__
    with open(STATE / 'requests.jsonl', 'a') as f:
        f.write(json.dumps(dict(rec, status=status, bytes=len(body), sha256=hashlib.sha256(body).hexdigest() if body else None, seconds=round(time.time() - t0, 3),
                                **({'failure': fail} if fail else {}))) + '\n')
    if fail: raise ProviderError(f'provider_error: PISTE {fail}')
    if len(body) > PISTE_MAX: raise ProviderError('provider_error: PISTE answer too large')
    return status, body


def piste_credentials():
    """(client id, secret) or PisteSkip; 0 request when absent or rejected earlier in the run."""
    if set(PISTE_KEYS) & sc.invalid_keys(STATE): raise PisteSkip('key_invalid', 'PISTE credentials rejected earlier in this run; the run goes on without PISTE')
    ci, cs_ = key('PISTE_CLIENT_ID'), key('PISTE_CLIENT_SECRET')
    if not (ci and cs_): raise PisteSkip('not_configured', 'PISTE_CLIENT_ID and PISTE_CLIENT_SECRET not both set (env or ~/.config/vp/, KEYS.md); 0 request')
    if not all(re.fullmatch(r'[\x21-\x7e]{4,}', x) for x in (ci, cs_)): raise PisteSkip('credential_invalid', 'PISTE credentials are not printable ASCII; never sent')
    return ci, cs_


def piste_token(force=False):
    """Bearer token: cached (same credentials, more than 60 s left) or fetched by client credentials (form body to the OAuth host)."""
    ci, cs_ = piste_credentials()
    f = STATE / PISTE_TOKEN; tag = hashlib.sha256((ci + '\0' + cs_).encode()).hexdigest()[:16]
    try: c = json.loads(f.read_text())
    except (OSError, ValueError): c = {}
    if not force and c.get('for') == tag and float(c.get('expires_at') or 0) > time.time() + 60 and c.get('access_token'): return c['access_token']
    form = urllib.parse.urlencode({'grant_type': 'client_credentials', 'client_id': ci, 'client_secret': cs_, 'scope': 'openid'}).encode()
    st, body = piste_http(PISTE_OAUTH, form, {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'}, cred='credentials')
    if st in (400, 401):
        for k in PISTE_KEYS: sc.mark_invalid(STATE, k)
        raise PisteSkip('key_invalid', f'PISTE refused the client credentials (HTTP {st}); the run goes on without PISTE')
    if st != 200: raise ProviderError(f'provider_error: PISTE OAuth HTTP {st}')
    try: r = json.loads(body); tok = r['access_token']; ttl = int(r.get('expires_in') or 3600)
    except (ValueError, KeyError, TypeError): raise ProviderError('provider_error: PISTE OAuth answer unreadable') from None
    if not re.fullmatch(r'[\x21-\x7e]{8,}', str(tok)): raise ProviderError('provider_error: PISTE token not printable ASCII')
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as w: json.dump({'for': tag, 'access_token': tok, 'expires_at': time.time() + ttl}, w)
    return tok


def piste_json(url, payload=None):
    """GET (payload None) or POST JSON to api.piste.gouv.fr with the bearer; cached by URL and body (never the token).
    401 -> one fresh token, then key_invalid; 403 -> not_subscribed; 404 -> None; 429 / 5xx -> ProviderError."""
    piste_credentials()                                                         # skipped first, even with a cached answer
    data = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode() if payload is not None else None
    cache = STATE / 'cache' / hashlib.sha256(b'piste\0' + url.encode() + b'\0' + (data or b'')).hexdigest()
    if cache.exists(): return json.loads(cache.read_bytes())
    for attempt in (0, 1):
        h = {'Authorization': 'Bearer ' + piste_token(force=attempt > 0), 'Accept': 'application/json', **({'Content-Type': 'application/json'} if data else {})}
        st, body = piste_http(url, data, h, cred='bearer')
        if st != 401: break
    if st == 401:
        for k in PISTE_KEYS: sc.mark_invalid(STATE, k)
        raise PisteSkip('key_invalid', 'PISTE refused the token twice (HTTP 401); the run goes on without PISTE')
    if st == 403: raise PisteSkip('not_subscribed', 'HTTP 403: the PISTE application is not subscribed to this API or its terms are not accepted (piste.gouv.fr)')
    if st == 404: return None
    if st == 429: raise ProviderError('rate_limited: PISTE HTTP 429')
    if st != 200: raise ProviderError(f'provider_error: PISTE HTTP {st}')
    try: r = json.loads(body)
    except ValueError: raise ProviderError('provider_error: PISTE answer is not JSON (not an empty result)') from None
    cache.parent.mkdir(parents=True, exist_ok=True); cache.write_bytes(body)
    return r


def piste_engine(search):
    """Turns PisteSkip into the skipped receipt (search: (receipt, reason); read: receipt)."""
    def deco(fn):
        def run(*a, **k):
            try: return fn(*a, **k)
            except PisteSkip as e: return (piste_skipped(e), e.reason + ': ' + e.detail) if search else piste_skipped(e)
        run.__name__ = fn.__name__; run.__doc__ = fn.__doc__
        return run
    return deco


# ---- Judilibre (Cour de cassation open data; taxonomy keys: jurisdiction cc|ca|tj|tcom, chamber civ1|civ2|civ3|comm|soc|cr|mi|pl|ordo...)
JL_COURT = {'cc': 'Cour de cassation', 'ca': "Cour d'appel", 'tj': 'Tribunal judiciaire', 'tcom': 'Tribunal de commerce'}
JL_CHAMBER = {'civ1': 'première chambre civile', 'civ2': 'deuxième chambre civile', 'civ3': 'troisième chambre civile', 'comm': 'chambre commerciale',
              'soc': 'chambre sociale', 'cr': 'chambre criminelle', 'mi': 'chambre mixte', 'pl': 'assemblée plénière', 'ordo': 'premier président'}
JL_ID = r'[A-Za-z0-9_-]{8,64}'
JL_OPERATIVE = re.compile(r'PAR\s+CES\s+MOTIFS', re.I)
JL_SET_ASIDE = re.compile(r'cass|annul|infirm', re.I)                        # solution of the later decision that sets this one aside


def jl_item(d, B):
    """Dated Judilibre record; barrier on decision_date (< T) and the ids (judilibre id, ECLI, appeal numbers) and title.
    Editorial metadata (publication level, summary, themes) is served only when the decision was last updated before T; when the update
    date is unknown (search results) it is served with metadata_as_of "today"; updated on/after T -> masked."""
    did, date = d.get('id'), d.get('decision_date')
    nums = [x for x in (d.get('numbers') or [d.get('number')]) if x]
    jur, ch = d.get('jurisdiction') or 'cc', d.get('chamber')
    title = f"{JL_COURT.get(jur, jur)}{', ' + JL_CHAMBER.get(ch, ch) if ch else ''}, {date}{', n° ' + nums[0] if nums else ''}"
    if not did or not law_ok(B, [did, 'judilibre:' + did, d.get('ecli')] + nums, [date], [title]): return None
    upd = d.get('update_date') or (d.get('update_datetime') or '')[:10] or None
    fresh = None if upd is None else bool(_before(upd, B))
    it = {'id': 'judilibre:' + did, 'ecli': d.get('ecli'), 'doi': None, 'number': nums[0] if nums else None, 'numbers': nums, 'title': title,
          'year': str(date)[:4], 'date': date, 'journal': 'Judilibre (Cour de cassation, PISTE)', 'court': jur, 'court_name': JL_COURT.get(jur, jur),
          'chamber': ch, 'formation': d.get('formation'), 'solution': d.get('solution_alt') if d.get('solution') == 'other' else d.get('solution'),
          'decision_type': d.get('type'), 'type': 'decision', 'tier': 'primary', 'order': 'FR-JUD', 'access': 'api',
          'date_updated': _before(upd, B) if upd else None}
    if fresh is False: it['metadata'] = 'decision updated on/after T: publication level, summary and themes masked'
    else:
        it.update(publication=d.get('publication'), bulletin=d.get('bulletin'), summary=(d.get('summary') or None), themes=d.get('themes'))
        if fresh is None: it['metadata_as_of'] = 'today (update date not exposed by the search: publication level and summary may postdate T)'
    return it


@piste_engine(search=True)
def search_judilibre(q, n, B, court=None, chamber=None, date_from=None, date_to=None):
    """Judilibre GET /search: decision date bounded on the provider side to [start, eve of T] (date_start/date_end), jurisdiction (cc by
    default on the provider side: cc, ca, tj, tcom) and chamber filters; 50 per page at most; every record rechecked by the barrier."""
    qq = ' '.join(q.split())
    if not qq: return [], 'empty query'
    if court and not re.fullmatch(r'cc|ca|tj|tcom', court): return [], 'court: Judilibre jurisdiction key expected (cc, ca, tj, tcom)'
    if chamber and not re.fullmatch(r'[a-z0-9]{1,8}', chamber): return [], 'chamber: Judilibre chamber key expected (civ1, civ2, civ3, comm, soc, cr, mi, pl...)'
    w, why = window(B, date_from, date_to)
    if why: return [], why
    exact = len(qq) > 2 and qq[0] == qq[-1] == '"'
    p = [('query', qq.strip('"') if exact else qq), ('operator', 'exact' if exact else 'and'), ('date_start', str(w[0])), ('date_end', str(w[1])),
         ('page_size', min(50, max(n, 10))), ('page', 0)] + ([('jurisdiction', court)] if court else []) + ([('chamber', chamber)] if chamber else [])
    r = piste_json(JUDILIBRE + 'search?' + urllib.parse.urlencode(p)) or {}
    out = [x for x in (jl_item(d, B) for d in r.get('results') or []) if x]
    return out[:n], (f"bounded: provider total {r.get('total')} (first page, {len(r.get('results') or [])} records, sorted by relevance and publication level"
                     f"{'; relaxed query' if r.get('relaxed') else ''}); decision dates {w[0]} to {w[1]}; jurisdiction {court or 'cc (provider default)'}"
                     f"{', chamber ' + chamber if chamber else ''}")


def jl_link(x, B):
    """A linked decision (contested, forward, timeline, rapprochement) kept only when dated before T."""
    if not isinstance(x, dict) or not _before(x.get('date'), B): return None
    return {k: x.get(k) for k in ('id', 'date', 'title', 'jurisdiction', 'chamber', 'solution', 'number') if x.get(k)}


@piste_engine(search=False)
def read_judilibre(did, B):
    """GET /decision?id=: the record, the decision text (head + operative part "PAR CES MOTIFS" when long, zone `dispositif` first) and its
    links dated before T. History: a later decision (forward) dated before T whose solution sets aside -> set_aside_by; forward dated before T
    otherwise -> set_aside_by [] (checked); forward on/after T or absent -> no history field (not_overturned: needs_confirmation, except cc)."""
    if not re.fullmatch(JL_ID, did): return {'refusal': 'expected form judilibre:<Judilibre decision id>'}
    d = piste_json(JUDILIBRE + 'decision?' + urllib.parse.urlencode({'id': did}))
    if not d or not d.get('id'): return {'refusal': 'not found'}
    it = jl_item(d, B)
    if not it: return {'refusal': 'after T or forbidden'}
    t = d.get('text') or ''
    z = next((s.get('start') for s in ((d.get('zones') or {}).get('dispositif') or []) if isinstance(s, dict) and isinstance(s.get('start'), int)), None)
    if z is None:
        m = None
        for m in JL_OPERATIVE.finditer(t): pass
        z = m.start() if m else None
    txt, how = head_tail(t, z)
    it.update(abstract=txt or '(no text available)', text_source=f'Judilibre (pseudonymised official text, {how})', visa=d.get('visa'),
              contested=jl_link(d.get('contested'), B), timeline=[y for y in (jl_link(x, B) for x in d.get('timeline') or []) if y],
              rapprochements=[y for y in (jl_link(x, B) for x in d.get('rapprochements') or []) if y])
    fw = jl_link(d.get('forward'), B)
    if fw:
        it['forward'] = fw; it['set_aside_by'] = [fw.get('id') or fw.get('number') or fw.get('title')] if JL_SET_ASIDE.search(str(fw.get('solution') or '')) else []
    elif d.get('forward'): it['history'] = 'later decision dated on/after T or undated: masked'
    return it


# ---- Legifrance (LEGI codes and consolidated laws/decrees, JORF). LEGI end of validity is EXCLUSIVE; 2999-01-01 = no end.
LF_FUND = {'code': 'CODE_DATE', 'loda': 'LODA_DATE', 'jorf': 'JORF'}
LF_ARTICLE = re.compile(r"(?i)\b(?:article|art\.)\s+((?:[LRDA]\.?\s*)?\d+(?:[-‑]\d+)*(?:\s+(?:bis|ter|quater|A|B|C))?)")


def lf_day(x):
    """Legifrance date -> 'YYYY-MM-DD': epoch milliseconds (a legal date at Paris midnight comes as 22:00/23:00 UTC the day before:
    rounded to the next day from 20:00 UTC), ISO string (first 10 characters), else None. Year >= 2999 -> '2999-01-01' (no end)."""
    if x is None or x == '': return None
    if isinstance(x, (int, float)) or re.fullmatch(r'-?\d{9,}', str(x)):
        try: t = dt.datetime.fromtimestamp(int(x) / 1000, dt.timezone.utc)
        except (OverflowError, OSError, ValueError): return '2999-01-01' if int(x) > 0 else None
        d = t.date() + dt.timedelta(days=1 if t.hour >= 20 else 0)
        return '2999-01-01' if d.year >= 2999 else d.isoformat()
    s = str(x)
    if not re.match(r'\d{4}', s): return None
    return '2999-01-01' if int(s[:4]) >= 2999 else s[:10]


def lf_item(lid, num, start, end, state, text_title, text_id, B, pre='legi:'):
    """One LEGI version: barrier on its start (< T) and ids/title; validity as known on the eve of T: an end on/after T is post-T knowledge
    (masked: valid_until None, validity "masked"), the state is the state on the eve (VIGUEUR when in force then; the recorded state when
    the version ended before T; MODIFIE_MORT_NE kept: never in force)."""
    vf, vu = lf_day(start), lf_day(end)
    title = f'{text_title}, article {num}' if num and text_title else text_title or (f'article {num}' if num else lid)
    if not law_ok(B, [lid, pre + lid, text_id], [vf], [title]): return None
    open_end = vu is None or vu >= '2999'
    masked = not open_end and not _before(vu, B)
    st = str(state or '').upper() or None
    live = open_end or masked                                                 # an end before T means the version had ended by the eve
    eve_state = st if st in ('MODIFIE_MORT_NE',) else 'VIGUEUR' if live else st
    return {'id': pre + lid, 'legi_id': lid, 'doi': None, 'title': title, 'year': vf[:4], 'date': vf, 'journal': 'Legifrance (PISTE)', 'type': 'text',
            'tier': 'primary', 'order': 'FR', 'access': 'api', 'text_id': text_id, 'number': num, 'version': lid,
            'valid_from': vf, 'applies_from': vf, 'valid_until': None if masked else (vu or '2999-01-01'), 'valid_until_exclusive': True,
            'legi_state': eve_state, 'in_force_on_eve_of_T': bool(live and eve_state != 'MODIFIE_MORT_NE'),
            'validity': 'end of validity on/after T: masked (no end before T)' if masked else 'LEGI version dates (end exclusive; 2999-01-01 = no end)'}


def jorf_item(r, B, title=None, tid=None):
    """JORF text as published: barrier on publication AND signature dates (< T)."""
    t0 = (r.get('titles') or [{}])[0]
    tid = tid or t0.get('cid') or t0.get('id') or r.get('cid') or r.get('id'); title = title or t0.get('title') or r.get('title')
    pub, sig = lf_day(r.get('datePublication') or r.get('dateParution')), lf_day(r.get('dateSignature') or r.get('dateTexte'))
    if not tid or not law_ok(B, [tid, 'jorf:' + tid, r.get('nor')], [pub, sig], [title]): return None
    return {'id': 'jorf:' + tid, 'doi': None, 'title': plain(title), 'year': sig[:4], 'date': sig, 'date_published': pub, 'journal': 'Journal officiel (Legifrance, PISTE)',
            'type': 'text', 'tier': 'primary', 'order': 'FR', 'access': 'api', 'nor': r.get('nor'), 'nature': r.get('nature'), 'version': tid,
            'validity': 'text as published in the JORF (not consolidated: read its legi: version for validity)'}


def lf_payload(q, fund, B, n):
    art = LF_ARTICLE.search(q); words = ' '.join((LF_ARTICLE.sub(' ', q) if art else q).replace('"', ' ').split())
    exact = q.strip()[:1] == q.strip()[-1:] == '"' and len(q.strip()) > 2
    champs = ([{'typeChamp': 'ALL', 'criteres': [{'typeRecherche': 'EXACTE' if exact else 'TOUS_LES_MOTS_DANS_UN_CHAMP', 'valeur': words, 'operateur': 'ET'}], 'operateur': 'ET'}] if words else []) + \
             ([{'typeChamp': 'NUM_ARTICLE', 'criteres': [{'typeRecherche': 'EXACTE', 'valeur': re.sub(r'\.\s*', '', art.group(1)), 'operateur': 'ET'}], 'operateur': 'ET'}] if art else [])
    noon = int(dt.datetime(B.eve.year, B.eve.month, B.eve.day, 12, tzinfo=dt.timezone.utc).timestamp() * 1000)   # the eve of T, unambiguous in Paris
    filt = [{'facette': 'DATE_VERSION', 'singleDate': noon}] if fund != 'JORF' else \
           [{'facette': k, 'dates': {'start': str(B.start), 'end': str(B.eve)}} for k in ('DATE_PUBLICATION', 'DATE_SIGNATURE')]
    return {'fond': fund, 'recherche': {'champs': champs, 'filtres': filt, 'pageNumber': 1, 'pageSize': min(max(n, 10), 100), 'operateur': 'ET',
                                        'sort': 'PERTINENCE' if fund != 'JORF' else 'PUBLICATION_DATE_DESC', 'typePagination': 'ARTICLE' if fund == 'CODE_DATE' else 'DEFAUT'}}


def lf_results(r, fund, B):
    out = []
    for x in (r or {}).get('results') or []:
        if fund == 'JORF':
            it = jorf_item(x, B)
            if it: out.append(it)
            continue
        t0 = (x.get('titles') or [{}])[0]; tt, tid = plain(t0.get('title')), t0.get('cid') or t0.get('id')
        arts = [e for s in x.get('sections') or [] for e in s.get('extracts') or [] if str(e.get('id') or '').startswith('LEGIARTI')]
        if arts: out += [y for y in (lf_item(e['id'], e.get('num'), e.get('dateDebut'), e.get('dateFin'), e.get('legalStatus'), tt, tid, B) for e in arts) if y]
        elif str(t0.get('id') or '').startswith('LEGITEXT'):
            y = lf_item(t0['id'], None, t0.get('startDate'), t0.get('endDate'), t0.get('legalStatus') or x.get('etat'), tt, None, B)
            if y: out.append(y)
    return out


@piste_engine(search=True)
def search_legifrance(q, n, B, fund=None):
    """Legifrance POST /search: codes (CODE_DATE) and consolidated laws/decrees (LODA_DATE) at the version in force on the eve of T
    (DATE_VERSION), interleaved; `fund` code|loda|jorf narrows (jorf: JORF texts published and signed in [start, eve of T]).
    "article 1382" in the query becomes an exact NUM_ARTICLE criterion; a query in quotes is an exact phrase."""
    if not q.strip(): return [], 'empty query'
    if fund and fund not in LF_FUND: return [], 'fund: code, loda or jorf expected'
    funds = [LF_FUND[fund]] if fund else ['CODE_DATE', 'LODA_DATE']
    parts, tots = [], []
    for f in funds:
        r = piste_json(LEGIFRANCE + 'search', lf_payload(q, f, B, n)) or {}
        parts.append(lf_results(r, f, B)); tots.append(f"{f} {r.get('totalResultNumber')}")
    mix = [y for t in zip(*parts) for y in t] if len(parts) > 1 else parts[0]
    mix += [y for p in parts for y in p[len(mix) // len(parts):]] if len(parts) > 1 else []
    seen, out = set(), []
    for y in mix:
        if y['id'] not in seen: seen.add(y['id']); out.append(y)
    return out[:n], (f"bounded: provider totals {', '.join(tots)} (first page each); "
                     + (f'published and signed {B.start} to {B.eve}' if fund == 'jorf' else f'version in force on {B.eve} (DATE_VERSION, eve of T)'))


def lf_flat(node, out, depth=0):
    """Article texts of a consult answer, in order (sections and their articles)."""
    for a in node.get('articles') or []:
        out.append((f"Article {a.get('num')}: " if a.get('num') else '') + plain(a.get('content') or a.get('texte') or a.get('texteHtml')))
    for s in node.get('sections') or []:
        if depth < 12: out.append(plain(s.get('title'))); lf_flat(s, out, depth + 1)
    return out


@piste_engine(search=False)
def read_legi(lid, B):
    """legi:LEGIARTI... -> the version of the article in force on the eve of T (POST /consult/getArticle, then the version picked among
    articleVersions: start <= eve < end, end exclusive); an article that ended before T -> its last version (state ABROGE/MODIFIE, end < T);
    an article first in force on/after T -> refused. legi:LEGITEXT... -> the text in force on the eve of T (POST /consult/legiPart, date = eve)."""
    if re.fullmatch(r'LEGITEXT\d{12}', lid):
        r = piste_json(LEGIFRANCE + 'consult/legiPart', {'textId': lid, 'date': str(B.eve)})
        if not r or not (r.get('title') or r.get('articles') or r.get('sections')): return {'refusal': 'not found'}
        it = lf_item(lid, None, r.get('dateDebutVersion') or r.get('dateTexte'), r.get('dateFinVersion'), r.get('etat'), plain(r.get('title')), None, B)
        if not it: return {'refusal': 'after T or forbidden'}
        t, how = head_tail('\n'.join(x for x in lf_flat(r, []) if x), None)
        return dict(it, abstract=t or '(no text available)', text_source=f'Legifrance consult/legiPart at {B.eve} ({how})')
    if not re.fullmatch(r'LEGIARTI\d{12}', lid): return {'refusal': 'expected form legi:LEGIARTI000006438834 (article) or legi:LEGITEXT000006070721 (text)'}
    a = ((piste_json(LEGIFRANCE + 'consult/getArticle', {'id': lid}) or {}).get('article')) or {}
    if not a.get('id'): return {'refusal': 'not found'}
    vs = [v for v in (a.get('articleVersions') or [{'id': a['id'], 'dateDebut': a.get('dateDebut'), 'dateFin': a.get('dateFin'), 'etat': a.get('etat')}]) if v.get('id')]
    eve = str(B.eve); started = sorted((v for v in vs if lf_day(v.get('dateDebut')) and lf_day(v['dateDebut']) <= eve), key=lambda v: lf_day(v['dateDebut']))
    if not started:
        B.excluded += 1; return {'refusal': 'after T: no version of this article in force before T'}
    pick = next((v for v in reversed(started) if (lf_day(v.get('dateFin')) or '2999-01-01') > eve and v.get('etat') != 'MODIFIE_MORT_NE'), started[-1])
    if pick['id'] != a['id']: a = ((piste_json(LEGIFRANCE + 'consult/getArticle', {'id': pick['id']}) or {}).get('article')) or {}
    if not a.get('id'): return {'refusal': 'not found (version in force on the eve of T)'}
    tt = (a.get('textTitles') or [{}])[0]
    it = lf_item(a['id'], a.get('num'), a.get('dateDebut'), a.get('dateFin'), a.get('etat'), plain(tt.get('titre') or tt.get('title')), tt.get('cid') or tt.get('id') or a.get('cidTexte'), B)
    if not it: return {'refusal': 'after T or forbidden'}
    versions = [{'id': v['id'], 'valid_from': lf_day(v.get('dateDebut')), 'valid_until': lf_day(v.get('dateFin')) if _before(lf_day(v.get('dateFin')), B) or (lf_day(v.get('dateFin')) or '') >= '2999' else None}
                for v in started]
    t, how = head_tail(plain(a.get('texte') or a.get('texteHtml')), None)
    return dict(it, id='legi:' + lid, version_requested=lid, versions_before_T=versions, abstract=t or '(no text available)', nota=plain(a.get('nota')) or None,
                text_source=f'Legifrance consult/getArticle, version in force on {B.eve} ({how})')


@piste_engine(search=False)
def read_jorf(tid, B):
    """jorf:JORFTEXT... -> the text as published in the Journal officiel (POST /consult/jorf); barrier on publication and signature dates."""
    if not re.fullmatch(r'JORFTEXT\d{12}', tid): return {'refusal': 'expected form jorf:JORFTEXT000033736934'}
    r = piste_json(LEGIFRANCE + 'consult/jorf', {'textCid': tid})
    if not r or not (r.get('title') or r.get('articles')): return {'refusal': 'not found'}
    it = jorf_item(r, B, plain(r.get('title')), tid)
    if not it: return {'refusal': 'after T or forbidden'}
    t, how = head_tail('\n'.join(x for x in lf_flat(r, []) if x), None)
    return dict(it, abstract=t or '(no text available)', text_source=f'Legifrance consult/jorf ({how})')


def read_piste(ident, B):
    p, _, v = ident.partition(':'); p = p.lower(); v = v.strip()
    return read_judilibre(v, B) if p == 'judilibre' else read_legi(v, B) if p == 'legi' else read_jorf(v, B)


PISTE_NO_CHAIN = 'citation chaining not served for judilibre:, legi:, jorf: identifiers'

SUBSCRIBE = 'identifiers accepted but the application is not subscribed to this API (piste.gouv.fr > Applications > tick {})'


def check_key(state):
    """Live check of the PISTE pair (setup_keys.py): token by client credentials, then one search each (Judilibre GET /search,
    Legifrance POST /search, codes) -> {label: 'ok' | 'refused' | ('fail', text) | exception}."""
    import datetime as _dt
    B, out = Barrier(_dt.date.today()), {}
    for label, run in (('Judilibre', lambda: search_judilibre('contrat', 1, B)), ('Légifrance', lambda: search_legifrance('contrat', 1, B, fund='code'))):
        try: r, note = run()
        except Exception as x: out[label] = x; continue
        if isinstance(r, list): out[label] = 'ok'; continue
        reason = r.get('reason')
        out[label] = 'refused' if reason in ('key_invalid', 'credential_invalid') else ('fail', SUBSCRIBE.format(label)) if reason == 'not_subscribed' else ('fail', f'not checked ({reason})')
    return out


JL = r'[A-Za-z0-9_-]{8,64}'
LEGI = r'LEGI(ARTI|TEXT)\d{12}'
JORF = r'JORFTEXT\d{12}'
SOURCE = {
    'name': 'piste', 'order': 190,
    'engines': {'judilibre': {'search': search_judilibre, 'options': ('court', 'chamber', 'date_from', 'date_to')},
                'legifrance': {'search': search_legifrance, 'options': ('fund',)}},
    'ids': [{'prefix': 'judilibre', 'form': JL, 'law_form': JL, 'export': 'case', 'export_rank': 50},
            {'prefix': 'legi', 'form': LEGI, 'law_form': LEGI, 'export': 'legislation', 'export_rank': 60},
            {'prefix': 'jorf', 'form': JORF, 'law_form': JORF, 'export': 'legislation', 'export_rank': 60}],
    'read': read_piste, 'citing': PISTE_NO_CHAIN, 'references': PISTE_NO_CHAIN, 'related': PISTE_NO_CHAIN,
    'plugins': ('law',), 'access': 'api',
    'hosts': {'oauth.piste.gouv.fr': {'interval': 1.0}, 'api.piste.gouv.fr': {'interval': 2.0}},   # law.md 5: 2 s local; published quota not established
    'terms': 'PISTE (piste.gouv.fr): free registration, subscription of the application to each API and acceptance of its terms (Judilibre, Legifrance)',
    'barrier': 'Judilibre: decision date bounded on the provider side to [start, eve of T], every record and link rechecked; Legifrance: the version in '
               'force on the eve of T (DATE_VERSION), an article first in force on/after T refused; JORF: publication and signature dates < T',
    'key': {'vars': PISTE_KEYS, 'send': 'oauth-client-credentials', 'hosts': (PISTE_HOST['credentials'],), 'token_hosts': (PISTE_HOST['bearer'],),
            'without': 'skipped', 'source': 'judilibre', 'engine': 'judilibre',
            'reason': 'Judilibre and Legifrance: 0 request, not_configured (token required by the service)', 'free': 'free, personal PISTE registration',
            'url': 'https://piste.gouv.fr/', 'suggest': ('Judilibre and Legifrance (PISTE)', '~5 min, then subscription to the APIs', True),
            'labels': ['Judilibre', 'Légifrance'], 'check': check_key,
            'prompt': {'PISTE_CLIENT_ID': 'PISTE Client ID', 'PISTE_CLIENT_SECRET': 'PISTE Client Secret'},
            'hint': 'create an application on piste.gouv.fr, subscribe it to the Judilibre and Légifrance APIs (production, accept their terms), '
                    'then copy its Client ID and Client Secret (piste.gouv.fr > Applications)',
            'refused': 'identifiers refused — check the Client ID and Client Secret (piste.gouv.fr > Applications)'},
}
