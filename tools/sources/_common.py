# SPDX-License-Identifier: Apache-2.0
"""Shared helpers of the sources (never a source itself): polite HTTP fetch with cache, per-host pacing, stop codes and the
generic key_invalid fallback; key resolution; the date barrier (Barrier, date_upper, year_before_T, law_ok / extra_ok); text helpers.
The host tables (INTERVAL, STOP, TIMEOUT, KEY_INTERVAL, KEY_REJECTED) are filled by the registry from each SOURCE['hosts'] and
SOURCE['key'] (sources/__init__.py: apply_hosts). Sources import what they use: `from sources._common import fetch, jget, Barrier`.
gateway.fetch = X / gateway.STATE = X (tests, tools) rebinds the same name here and in every source module (sources.rebind)."""
import datetime as dt
import fcntl
import hashlib
import html
import json
import os
import pathlib
import re
import sys
import time
import urllib.error, urllib.parse, urllib.request

P = pathlib.Path(__file__).resolve().parent.parent   # tools/
if str(P) not in sys.path: sys.path.insert(0, str(P))
import code_sources as sc   # noqa: E402  (key(), invalid_keys(), mark_invalid(): one key rule for the whole skill)

CFG = json.loads((P / 'config.json').read_text())
CASES_FILE = P.parent / 'tests' / 'fixtures' / 'bench_cases.json'   # date-barrier cases, data only, tests and --case only
STATE = pathlib.Path(os.environ.get('VP_STATE') or 'vp-state')


def _ua():
    # Identification contact: env VP_CONTACT (a team or project address, never a personal address by default).
    # Without it, a generic identification with no e-mail; sources that require a contact are skipped with a receipt.
    c = os.environ.get('VP_CONTACT', '').strip()
    return {'User-Agent': 'VanishingPoint/1 (+' + c + ')' if c else 'VanishingPoint/1 (research skill)'}


def _mailto(sep='&'):
    """Crossref polite-pool contact: only the VP_CONTACT value, never a literal address."""
    c = os.environ.get('VP_CONTACT', '').strip()
    return sep + 'mailto=' + urllib.parse.quote(c) if c else ''


UA = _ua()
INTERVAL = {}       # host -> seconds between two calls (SOURCE['hosts'][host]['interval']; default 0.3)
TIMEOUT = {}        # host -> seconds (SOURCE['hosts'][host]['timeout']; default 40)
STOP = {}           # host -> HTTP codes (or 'timeout') that stop at once, no retry (SOURCE['hosts'][host]['stop']); level-2 `page` hosts: 403/429
KEY_INTERVAL = {}   # host -> (variable, seconds) when that key is live (SOURCE['key']['interval_with_key'])


key = sc.key   # single key rule (code_sources.key, KEYS.md): env NAME, then ~/.config/vp/<name lowercase>.key


def live_key(name):
    """key(name) unless the provider rejected it earlier in this run (<state>/keys-invalid.json): then None, the source goes on without it."""
    return None if name in sc.invalid_keys(STATE) else key(name)


# host -> (variable, HTTP codes meaning "key rejected", markers required in the body) (SOURCE['key']['rejected'], keys sent as api_key=);
# the body is read, never logged (NCBI echoes the key)
KEY_REJECTED = {}


def strip_key(url):
    """The same URL without its api_key= parameter."""
    return re.sub(r'\?api_key=[^&]*&?', '?', re.sub(r'&api_key=[^&]*', '', url)).rstrip('?')


def interval(host):
    """Seconds between two calls to a host; a declared faster pace while a key is live (E-utilities: 0.11 s with a key instead of 0.45)."""
    kv = KEY_INTERVAL.get(host)
    if kv and live_key(kv[0]): return kv[1]
    return INTERVAL.get(host, 0.3)


def fetch(url, headers=None):
    host = urllib.parse.urlparse(url).netloc
    cache = STATE / 'cache' / hashlib.sha256((url + (json.dumps(headers, sort_keys=True) if headers else '')).encode()).hexdigest()
    if cache.exists():
        return cache.read_bytes()
    STATE.mkdir(parents=True, exist_ok=True)
    lock = STATE / f'rate-{host}.lock'
    for attempt in range(5):
        with open(lock, 'a+') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0); last = float(f.read() or 0)
            wait = last + interval(host) - time.time()
            if wait > 0: time.sleep(wait)
            f.seek(0); f.truncate(); f.write(str(time.time()))
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=dict(UA, **(headers or {}))), timeout=TIMEOUT.get(host, 40)) as r:
                data = r.read()
            cache.parent.mkdir(parents=True, exist_ok=True); cache.write_bytes(data)
            return data
        except Exception as e:
            code = getattr(e, 'code', None) or ('timeout' if isinstance(e, TimeoutError) or isinstance(getattr(e, 'reason', None), TimeoutError) else None)
            rej = KEY_REJECTED.get(host)
            if rej and code in rej[1] and 'api_key=' in url and (lambda b: any(m in b for m in rej[2]))((e.read() or b'').lower()):   # key rejected: once without it, then key-less
                sc.mark_invalid(STATE, rej[0]); url = strip_key(url)
                cache = STATE / 'cache' / hashlib.sha256((url + (json.dumps(headers, sort_keys=True) if headers else '')).encode()).hexdigest()
                if cache.exists(): return cache.read_bytes()
                continue
            if attempt == 4 or code in STOP.get(host, ()): raise
            time.sleep(2 + 3 * attempt)


def jget(url): return json.loads(fetch(url))


def date_upper(s):
    """Partial ISO date -> UPPER bound (no precision is fabricated)."""
    if not s: return None
    s = str(s)
    MO = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
    mm = re.match(r'^(\d{4})\s+([A-Za-z]{3})[a-z]*(?:\s+(\d{1,2}))?', s)
    if mm and mm.group(2).lower() in MO:
        parts = [int(mm.group(1)), MO.index(mm.group(2).lower()) + 1] + ([int(mm.group(3))] if mm.group(3) else [])
    else:
        mi = re.match(r'^\s*(\d{4})(?:[-/](\d{1,2}))?(?:[-/](\d{1,2}))?', s)
        parts = [int(x) for x in mi.groups() if x] if mi else []
    if not parts: return None
    y = parts[0]; m = parts[1] if len(parts) > 1 else 12; day = parts[2] if len(parts) > 2 else 28 if m == 2 else 30
    try: return dt.date(y, m, day)
    except ValueError: return dt.date(y, m, 28)


def tokens(t):
    import unicodedata
    t = unicodedata.normalize('NFKD', str(t)).encode('ascii', 'ignore').decode().lower()
    return {w for w in re.findall(r'[a-z0-9]+', t) if len(w) >= 3}


def title_sim(a, b):
    """Overlap relative to the shorter title (a truncated or extended copy of the forbidden title stays blocked)."""
    return len(a & b) / max(1, min(len(a), len(b))) if min(len(a), len(b)) >= 4 else float(a == b and bool(a))


class Barrier:
    """T (date of the question), forbidden DOIs and titles, optional lower bound."""

    def __init__(self, T, forbidden_dois=(), forbidden_titles=(), since=None):
        self.T = T if isinstance(T, dt.date) else dt.date.fromisoformat(str(T)[:10])
        self.forbidden = {x.lower() for x in forbidden_dois}
        self.titles = [tokens(t) for t in forbidden_titles]
        self.since = int(since) if since else None
        self.excluded = 0

    @classmethod
    def from_case(cls, case_id):
        """Date-barrier case from tests/fixtures/bench_cases.json (tests and --case only; the file is optional)."""
        if not CASES_FILE.exists():
            raise ValueError('no case table: ' + CASES_FILE.name + ' is absent')
        c = json.loads(CASES_FILE.read_text())[case_id]
        return cls(c['T'], c['forbidden_dois'], c.get('forbidden_titles', []))

    def ok(self, doi=None, *dates, title=None):
        if doi and doi.lower().replace('https://doi.org/', '') in self.forbidden: self.excluded += 1; return False
        if title and any(title_sim(tokens(title), t) >= CFG['review_title_threshold'] for t in self.titles): self.excluded += 1; return False
        ds = [date_upper(x) for x in dates]
        if not ds or any(x is None for x in ds) or any(x >= self.T for x in ds): self.excluded += 1; return False
        if self.since and max(ds).year < self.since: self.excluded += 1; return False
        return True

    @property
    def eve(self): return self.T - dt.timedelta(days=1)

    @property
    def start(self): return dt.date(self.since, 1, 1) if self.since else dt.date(1800, 1, 1)


def year_before_T(year, B):
    """A reference known only by its year: kept when the year (first four digits) is strictly before the year of T, else '9999'
    (refused). A missing or non-numeric year ('n.d.', '2020a' is read as 2020) never raises."""
    m = re.match(r'\s*(\d{4})', str(year or ''))
    return m.group(1) if m and int(m.group(1)) < B.T.year else '9999'


# ---------------------------------------------------------------- law engines (plugins/law.md, sections 1, 2, 4, 7, 13)

class ProviderError(RuntimeError):
    """Typed provider failure (e.g. Cellar HTTP 500 "VECSL internal error"): never read as an empty result."""


def law_ok(B, ids, dates, titles=()):
    """Barrier for law records: forbidden identifiers (DOI, CELEX, ECLI, NNT, HAL id; same list as the DOIs) and titles,
    then every date (act, decision, defence, deposit) < T through B.ok; no usable date -> refused (strict)."""
    if any(i and str(i).lower().replace('https://doi.org/', '') in B.forbidden for i in ids) or \
       any(t and any(title_sim(tokens(t), f) >= CFG['review_title_threshold'] for f in B.titles) for t in titles):
        B.excluded += 1; return False
    return B.ok(None, *dates)


def _before(x, B):
    """A date string strictly before T (upper bound of a partial date), else None (masked)."""
    return x if x and date_upper(x) and date_upper(x) < B.T else None


TEXT_HEAD = 20000      # characters of an official text served from its start (Cellar, administrative courts)
OPERATIVE_MAX = 20000  # characters of the operative part appended when the judgment is longer than TEXT_HEAD
OPERATIVE = re.compile(r'(On those grounds,?\s+(the\s+)?(Court|General Court|Tribunal)\b[^:]{0,160}?\bhereby\b'
                       r'|Par ces motifs,?\s+(la\s+Cour|le\s+Tribunal)\b[^:]{0,160}?(dit pour droit|d[ée]clare|ordonne|d[ée]cide|rejette|annule))', re.I)


def head_and_operative(t, case_law):
    """(text served, how): the whole text when it fits in TEXT_HEAD; else its start, and for case law the operative part
    ("On those grounds, the Court ... hereby rules" / "Par ces motifs") appended after an explicit elision mark."""
    if len(t) <= TEXT_HEAD: return t, 'whole'
    m = None
    for m in (OPERATIVE.finditer(t) if case_law else ()): pass                 # the last one: the operative part closes the judgment
    if m is None or m.start() < TEXT_HEAD:
        return t[:TEXT_HEAD] + f' [... text cut at {TEXT_HEAD:,} of {len(t):,} characters ...]', 'start'
    tail = t[m.start():m.start() + OPERATIVE_MAX]
    return (t[:TEXT_HEAD] + f' [... characters {TEXT_HEAD:,} to {m.start():,} of {len(t):,} elided; operative part follows ...] ' + tail
            + (f' [... cut at {OPERATIVE_MAX:,} characters of the operative part ...]' if len(t) - m.start() > OPERATIVE_MAX else '')), 'start + operative part'


def dmy(s):
    """theses.fr dd/mm/yyyy -> ISO (a lone year stays a year: no precision is fabricated)."""
    m = re.fullmatch(r'\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*', str(s or ''))
    if m: return f'{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}'
    m = re.fullmatch(r'\s*(\d{4})(-\d{2}(-\d{2})?)?\s*', str(s or ''))
    return m.group(0).strip() if m else None


def extra_ok(B, ids, dates, titles=()):
    """Barrier of the extra engines: forbidden identifiers (same list as the DOIs) and titles, then every date < T through B.ok."""
    if any(i and str(i).lower().replace('https://doi.org/', '') in B.forbidden for i in ids) or \
       any(t and any(title_sim(tokens(t), f) >= CFG['review_title_threshold'] for f in B.titles) for t in titles):
        B.excluded += 1; return False
    return B.ok(None, *dates)


def http_code(e): return getattr(e, 'code', None)


def window(B, date_from=None, date_to=None):
    """(lo, hi) inside [start, eve of T] or (None, reason)."""
    lo, hi = B.start, B.eve
    for v, side in ((date_from, 'from'), (date_to, 'to')):
        if v is None: continue
        try: d = dt.date.fromisoformat(v)
        except (TypeError, ValueError): return None, f'{side}: date YYYY-MM-DD expected'
        if side == 'from': lo = max(lo, d)
        else: hi = min(hi, d)
    return ((lo, hi), None) if lo <= hi else (None, f'empty window ({lo} > {hi}; the end is at most the eve of T)')


def plain(s): return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', str(s or ''))).split())


def head_tail(t, z, what='operative part'):
    """Whole text when it fits in TEXT_HEAD; else its start, and from offset z (operative part) after an explicit elision mark."""
    if len(t) <= TEXT_HEAD: return t, 'whole'
    if z is None or z < TEXT_HEAD: return t[:TEXT_HEAD] + f' [... text cut at {TEXT_HEAD:,} of {len(t):,} characters ...]', 'start'
    return (t[:TEXT_HEAD] + f' [... characters {TEXT_HEAD:,} to {z:,} of {len(t):,} elided; {what} follows ...] ' + t[z:z + OPERATIVE_MAX]
            + (f' [... cut at {OPERATIVE_MAX:,} characters of the {what} ...]' if len(t) - z > OPERATIVE_MAX else '')), f'start + {what}'


# Verbatim "not served" messages of the built-in sources (kept identical for unchanged outputs; a new source writes its own).
LAW_NO_CHAIN = 'citation chaining not served for law identifiers (Cellar work_cites_work: not wired)'
EXTRA_NO_CHAIN = 'citation chaining not served for nct:, dblp:, econbiz:, osv: identifiers (read the DOI)'
RELATED_ONLY = 'related works served only for doi:, pmid:, arxiv: or OpenAlex W identifiers'


def preprint_unless_venue(ident, venue):
    """Export type of a repository identifier (arXiv, HAL, OpenReview): 'preprint' without a venue, else 'article'."""
    return 'article' if venue else 'preprint'


def value(ident):
    """'prefix:value' -> value, stripped (the part a source's read receives after its prefix)."""
    return ident.partition(':')[2].strip()
