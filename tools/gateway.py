#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Dated gateway of VanishingPoint (non-leak measured on our benches: 19/19 cases).
The only document access of the engine. Refuses every document dated >= T (publication AND indexing when available),
the forbidden DOIs and titles, and the engines that no plugin declared.

Command line:
  gateway.py [--plugin P.md ...] [--T YYYY-MM-DD | --case ID] [--run NAME] [--state DIR] [--cap N] [--since YEAR]
             <command> <argument> [--n N]
  commands: sources | search-<engine> "<query>" | read <id> | citing <id> | references <id> | related <id> (OpenAlex related works, same barrier)
  wired engines: pubmed, europepmc, crossref, openalex, arxiv   (id: pmid:NNN | doi:10.x | arxiv:2501.01234)
  law engines (plugins/law.md): eurlex, justice-administrative [--court CE|TA75|CAA69] [--from YYYY-MM-DD] [--to YYYY-MM-DD], hal, theses-fr
    (id: celex:32016R0679 | ecli:ECLI:EU:... | ecli:ECLI:FR:... | ja:<court>/<file> | hal:hal-0123 | thesesfr:<nnt>)
  code engines (code_sources.py; served only when a plugin declares them): search-code "<pattern>" [--language L] [--repo owner/repo] |
    versions <pypi|npm|cargo>:<package>@<version> | paper-code <arxiv> | provenance <origin https://... | swh:1:...>
  extra keyless engines: clinicaltrials (biology), dblp (cs-ai), econbiz (finance)   (id: nct:NCT01234567 | dblp:conf/acl/Xiong0LZ24 | econbiz:10011386660);
    code engine osv: vulns <pypi|npm|cargo|go|maven|rubygems|nuget|packagist>:<package>@<version> ; read osv:<id>
  preprint engines (plugins/biology.md): biorxiv, medrxiv (Europe PMC words, versions dated on api.biorxiv.org; id doi:<preprint DOI>; read biorxiv:<DOI> | medrxiv:<DOI>)
  CS engines (plugins/cs-ai.md, v0.4.6): hf-models, hf-datasets (read hfmodel:<owner/name> | hfdataset:<owner/name>: card at the last commit before T),
    standards (rfc:<n> | pep:<n> | w3c:<shortname>), proceedings (acl:<Anthology id> | pmlr:v<vol>/<key> | cvf:content/<CONF>/html/<name>_paper)
  PISTE engines (plugins/law.md, credentials PISTE_CLIENT_ID + PISTE_CLIENT_SECRET, else skipped with 0 request): judilibre [--court cc|ca|tj|tcom]
    [--chamber civ1|soc|cr...] [--from] [--to], legifrance [--fund code|loda|jorf] (read judilibre:<id> | legi:LEGIARTI.../LEGITEXT... | jorf:JORFTEXT...)
  AI engines (plugins/cs-ai.md): openreview, zenodo, hal-info (id: openreview:<forum id> | zenodo:<record id>); code engine usage <pypi|npm|cargo|...>:<package> (ecosyste.ms)
  A key the provider rejects (NCBI 400 "API key invalid" or "not wellformed", OpenAlex 401/403, Software Heritage 401/403) is dropped for the rest of the run
  (<state>/keys-invalid.json, names only), the call is retried once without it, and every answer carries key_invalid: [NAME].
Import:
  from gateway import Gateway
  g = Gateway(plugins=['plugins/cs-ai.md'], T='2026-10-26', run='q1')
  g.search('openalex', 'query', n=20) ; g.read('doi:...') ; g.citing('pmid:...') ; g.references('arxiv:...') ; g.related('doi:...')

`sources` block read in each plugin (in its Sources section, fenced ```sources):
  engines: openalex, crossref, arxiv      # required ; engines that are not wired are tolerated but refused when called
  since: 2015                             # optional lower bound (year)
  cap: 60                                 # optional safety cap on calls
  keys: OPENALEX_KEY                      # optional, resolved by key() (env NAME, ~/.config/vp/<name>.key ; KEYS.md), never required
Without plugin: every wired engine. Default T: today (nothing later than yesterday is served).
--case ID (tests only): T, forbidden DOIs and titles from tests/fixtures/bench_cases.json, loaded only when that file exists.
"""
import argparse, datetime as dt, fcntl, hashlib, html, json, os, pathlib, re, sys, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P)); import code_sources as sc   # python3 -I does not add the script directory
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
INTERVAL = {'api.opencitations.net': 0.4, 'eutils.ncbi.nlm.nih.gov': 0.45, 'www.ebi.ac.uk': 0.25, 'api.crossref.org': 0.25,
            'api.openalex.org': 0.2, 'export.arxiv.org': 3.0,
            'publications.europa.eu': 2.0, 'opendata.justice-administrative.fr': 3.0, 'api.archives-ouvertes.fr': 1.0, 'theses.fr': 5.0}   # law.md rates
# HTTP codes that stop at once (no retry): level-2 `page` hosts stop on 403/429 (ACCESS-POLICY.md); Cellar 500 = provider_error
TIMEOUT = {'publications.europa.eu': 90}   # Cellar: a first free-text query on a common word can take ~60-90 s (measured 2026-10-28), then is fast
STOP = {'opendata.justice-administrative.fr': (403, 429), 'theses.fr': (403, 429), 'publications.europa.eu': (400, 500, 'timeout'), 'api.archives-ouvertes.fr': (400,)}
NS = {'a': 'http://www.w3.org/2005/Atom', 'x': 'http://arxiv.org/schemas/atom', 'os': 'http://a9.com/-/spec/opensearch/1.1/'}


key = sc.key   # single key rule (code_sources.key, KEYS.md): env NAME, then ~/.config/vp/<name lowercase>.key


def live_key(name):
    """key(name) unless the provider rejected it earlier in this run (<state>/keys-invalid.json): then None, the source goes on without it."""
    return None if name in sc.invalid_keys(STATE) else key(name)


# host -> (variable, HTTP codes meaning "key rejected", marker required in the body); the body is read, never logged (NCBI echoes the key)
# NCBI: 400 "API key invalid", or "API key not wellformed" for any mistyped key (measured 2026-10-28; the old marker missed it: 5 retries then failure)
KEY_REJECTED = {'eutils.ncbi.nlm.nih.gov': ('NCBI_API_KEY', (400,), (b'api key invalid', b'api key not wellformed')), 'api.openalex.org': ('OPENALEX_KEY', (401, 403), (b'',))}


def strip_key(url):
    """The same URL without its api_key= parameter."""
    return re.sub(r'\?api_key=[^&]*&?', '?', re.sub(r'&api_key=[^&]*', '', url)).rstrip('?')


def ncbi_key():
    """NCBI_API_KEY as an E-utilities `api_key=` parameter (10 req/s instead of 3); '' without a key."""
    k = live_key('NCBI_API_KEY')
    return '&api_key=' + urllib.parse.quote(k) if k else ''


def interval(host):
    """Seconds between two calls to a host; E-utilities allow 10 req/s with a key (0.11 s) instead of 3 (0.45 s)."""
    if host == 'eutils.ncbi.nlm.nih.gov' and live_key('NCBI_API_KEY'): return 0.11
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
            if attempt == 4 or (host == 'api.openalex.org' and code == 429) or code in STOP.get(host, ()): raise
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


# ---------------------------------------------------------------- engines

def pubmed_summ(ids, B):
    if not ids: return []
    s = jget('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id=' + ','.join(ids) + ncbi_key())['result']
    out = []
    for i in ids:
        r = s.get(i, {})
        doi = next((a['value'] for a in r.get('articleids', []) if a.get('idtype') == 'doi'), None)
        hist = {h['pubstatus']: h['date'] for h in r.get('history', [])}
        dates = [hist.get('entrez'), r.get('epubdate') or r.get('sortpubdate')]
        if not B.ok(doi, *dates, title=r.get('title')): continue
        out.append({'id': f'pmid:{i}', 'doi': doi, 'title': r.get('title'), 'year': (r.get('pubdate') or '')[:4],
                    'journal': r.get('source'), 'first_author': (r.get('authors') or [{}])[0].get('name')})
    return out


def search_pubmed(q, n, B):
    url = (f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmode=json&sort=relevance&datetype=edat&mindate={B.start:%Y/%m/%d}'
           f'&maxdate={B.eve:%Y/%m/%d}&retmax={n}&term=' + urllib.parse.quote(q) + ncbi_key())
    r = jget(url)['esearchresult']
    return pubmed_summ(r.get('idlist', []), B), int(r.get('count', 0))


def epmc_item(r, B):
    if not B.ok(r.get('doi'), r.get('firstIndexDate'), r.get('firstPublicationDate') or r.get('pubYear'), title=r.get('title')):
        return None
    ident = f"pmid:{r['pmid']}" if r.get('pmid') else (f"doi:{r['doi']}" if r.get('doi') else r.get('id'))
    return {'id': ident, 'doi': r.get('doi'), 'title': r.get('title'), 'year': r.get('pubYear'), 'journal': r.get('journalTitle'),
            'first_author': (r.get('authorString') or '').split(',')[0], 'type': r.get('pubType')}


def search_europepmc(q, n, B):
    qq = f'({q}) AND FIRST_IDATE:[{B.start} TO {B.eve}]'
    r = jget('https://www.ebi.ac.uk/europepmc/webservices/rest/search?format=json&resultType=lite&pageSize=' + str(n) + '&query=' + urllib.parse.quote(qq))
    out = [x for x in (epmc_item(i, B) for i in r.get('resultList', {}).get('result', [])) if x]
    return out, r.get('hitCount')


def cr_item(it, B):
    issued = '-'.join(str(x) for x in ((it.get('issued', {}).get('date-parts') or [[None]])[0] or []) if x)
    if not B.ok(it.get('DOI'), issued, (it.get('created') or {}).get('date-time'), title=(it.get('title') or [''])[0]): return None
    return {'id': 'doi:' + it['DOI'], 'title': (it.get('title') or [''])[0], 'year': issued[:4],
            'journal': (it.get('container-title') or [''])[0], 'first_author': ((it.get('author') or [{}])[0]).get('family'), 'type': it.get('type')}


def search_crossref(q, n, B):
    since = f',from-pub-date:{B.start}' if B.since else ''
    url = (f'https://api.crossref.org/works?rows={n}&filter=until-created-date:{B.eve},until-pub-date:{B.eve}{since}'
           '&select=DOI,title,issued,created,container-title,author,type&query.bibliographic=' + urllib.parse.quote(q) + _mailto())
    m = jget(url)['message']
    return [x for x in (cr_item(i, B) for i in m.get('items', [])) if x], m.get('total-results')


def oa_item(w, B):
    doi = (w.get('doi') or '').replace('https://doi.org/', '') or None
    if not B.ok(doi, w.get('publication_date'), title=w.get('title')): return None
    return {'id': f'doi:{doi}' if doi else w['id'].rsplit('/', 1)[-1], 'title': w.get('title'), 'year': w.get('publication_year'),
            'journal': ((w.get('primary_location') or {}).get('source') or {}).get('display_name'), 'type': w.get('type')}


OASEL = 'id,doi,title,publication_date,publication_year,primary_location,type'


def year_before_T(year, B):
    """A reference known only by its year: kept when the year (first four digits) is strictly before the year of T, else '9999'
    (refused). A missing or non-numeric year ('n.d.', '2020a' is read as 2020) never raises."""
    m = re.match(r'\s*(\d{4})', str(year or ''))
    return m.group(1) if m and int(m.group(1)) < B.T.year else '9999'


def oa_key():
    k = live_key('OPENALEX_KEY')
    return '&api_key=' + urllib.parse.quote(k) if k else ''


def crossref_deposit(items, B):
    """OpenAlex has no reliable indexing date: every returned DOI is rechecked on Crossref (deposit AND publication < T).
    Without DOI, or DOI absent from Crossref: refused (strict)."""
    dois = [x['id'][4:] for x in items if x['id'].startswith('doi:')]
    ok = set()
    for i in range(0, len(dois), 40):
        f = ','.join('doi:' + x for x in dois[i:i + 40])
        m = jget('https://api.crossref.org/works?rows=100&select=DOI,title,issued,created&filter=' + urllib.parse.quote(f, safe=':,') + _mailto())['message']
        ok |= {it['DOI'].lower() for it in m.get('items', []) if cr_item(it, B)}
    kept = [x for x in items if x['id'].startswith('doi:') and x['id'][4:].lower() in ok]
    B.excluded += len(items) - len(kept)
    return kept


def search_openalex(q, n, B, filt=''):
    try: return _search_openalex(q, n, B, filt)
    except Exception as e:
        if filt or not q: raise
        out, tot = search_crossref(q, n, B)
        return out, f'OpenAlex unavailable ({str(e)[:40]}): Crossref fallback, total {tot}'


def _search_openalex(q, n, B, filt=''):
    since = f',from_publication_date:{B.start}' if B.since else ''
    url = (f'https://api.openalex.org/works?per_page={n}&select={OASEL}&filter=to_publication_date:{B.eve}{since}{filt}'
           + ('&search=' + urllib.parse.quote(q) if q else '') + oa_key())
    r = jget(url)
    return crossref_deposit([x for x in (oa_item(w, B) for w in r.get('results', [])) if x], B), r.get('meta', {}).get('count')


def oa_work(ident):
    if ident.lower().startswith('arxiv:'): ident = 'doi:10.48550/arXiv.' + ident[6:]
    if ident.startswith('doi:'): return jget('https://api.openalex.org/works/doi:' + urllib.parse.quote(ident[4:]) + ('?' + oa_key()[1:] if oa_key() else ''))
    if ident.startswith('pmid:'): return jget('https://api.openalex.org/works/pmid:' + ident[5:])
    return jget('https://api.openalex.org/works/' + ident)


def arxiv_item(e, B, with_abstract=False):
    aid = (e.findtext('a:id', default='', namespaces=NS)).rsplit('/', 1)[-1]
    base = re.sub(r'v\d+$', '', aid)
    pub = e.findtext('a:published', default='', namespaces=NS)
    title = ' '.join((e.findtext('a:title', default='', namespaces=NS)).split())
    doi = e.findtext('x:doi', default=None, namespaces=NS)
    upd = e.findtext('a:updated', default='', namespaces=NS)
    # publication (v1) AND last version < T: the abstract served is the one of the version received (frozen rule of the non-medical gateway)
    if not B.ok(doi, pub, upd or pub, title=title): return None
    it = {'id': f'arxiv:{base}', 'arxiv': base, 'doi': doi, 'title': title, 'year': pub[:4], 'journal': 'arXiv',
          'first_author': e.findtext('a:author/a:name', default='', namespaces=NS), 'date_published': pub[:10],
          'date_version': (e.findtext('a:updated', default='', namespaces=NS))[:10]}
    if with_abstract: it['abstract'] = ' '.join((e.findtext('a:summary', default='', namespaces=NS)).split())[:6000]
    return it


def search_arxiv(q, n, B):
    """arXiv search (Atom API) bounded on the provider side by submission date; local recheck on "published" (v1) < T."""
    sq = f'({q}) AND submittedDate:[{B.start:%Y%m%d}0000 TO {B.eve:%Y%m%d}2359]'
    root = ET.fromstring(fetch('https://export.arxiv.org/api/query?' + urllib.parse.urlencode({'search_query': sq, 'max_results': n, 'sortBy': 'relevance'})))
    out = [x for x in (arxiv_item(e, B) for e in root.findall('a:entry', NS)) if x]
    return out, root.findtext('os:totalResults', default=None, namespaces=NS)


def read_arxiv(ident, B):
    """Explicit reading of v1: notice and abstract dated from the initial deposit (< T required)."""
    aid = re.sub(r'v\d+$', '', ident[6:].strip()) + 'v1'
    root = ET.fromstring(fetch('https://export.arxiv.org/api/query?' + urllib.parse.urlencode({'id_list': aid})))
    for e in root.findall('a:entry', NS):
        it = arxiv_item(e, B, with_abstract=True)
        return it or {'refusal': 'after T or forbidden'}
    return {'refusal': 'not found'}


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


CELLAR = 'https://publications.europa.eu/webapi/rdf/sparql'
CDM = 'PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>\nPREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n'
EU_LANG = 'http://publications.europa.eu/resource/authority/language/'
CELEX_FORM = r'[0-9][0-9A-Z()_.\-]{4,40}'


def sparql(q):
    """Cellar SPARQL (GET, JSON). HTTP 5xx or unreadable answer -> ProviderError (law.md: VECSL 500 = provider_error, not empty)."""
    try: r = json.loads(fetch(CELLAR + '?' + urllib.parse.urlencode({'query': q, 'format': 'application/sparql-results+json'})))
    except urllib.error.HTTPError as e:
        if e.code >= 500: raise ProviderError(f'provider_error: Cellar HTTP {e.code} (not an empty result)')
        raise
    except ValueError: raise ProviderError('provider_error: Cellar answer is not JSON (not an empty result)')
    except (TimeoutError, urllib.error.URLError) as e: raise ProviderError(f'provider_error: Cellar unreachable or timeout ({str(e)[:60]})')
    return [{k: v.get('value') for k, v in b.items()} for b in r.get('results', {}).get('bindings', [])]


def eu_kept(celex):
    """Sectors 0 (consolidated), 3 (legislation), 6 (case law); Advocate General opinions (6....CC), _RES/_INF and the OJ notices of a judgment
    (6....CA/TA/FA, a duplicate of the ruling, not its text) set aside (law.md 1-2)."""
    return bool(re.match(r'^[036]', celex)) and not re.match(r'^6\d{4}(CC|[CTF]A)', celex) and '_RES' not in celex and '_INF' not in celex


def eu_details(celexes):
    """Per CELEX (twins grouped): dates, entry into force, end of validity, flag, lastModificationDate, ECLI, both "declares void"
    predicates read from the voiding rulings with their dates. One property per UNION branch: no OPTIONAL join (the ELI trap)."""
    if not celexes: return {}
    vals = ' '.join('"%s"^^xsd:string' % c for c in celexes)
    q = CDM + ('SELECT DISTINCT ?celex ?k ?v ?d WHERE { VALUES ?celex { %s } ?w cdm:resource_legal_id_celex ?celex .\n'
               '{ ?w cdm:work_date_document ?v BIND("date" AS ?k) } UNION { ?w cdm:resource_legal_date_entry-into-force ?v BIND("eif" AS ?k) }\n'
               'UNION { ?w cdm:resource_legal_date_end-of-validity ?v BIND("eov" AS ?k) } UNION { ?w cdm:resource_legal_in-force ?v BIND("flag" AS ?k) }\n'
               'UNION { ?w <http://publications.europa.eu/ontology/cdm/cmr#lastModificationDate> ?v BIND("lmd" AS ?k) } UNION { ?w cdm:case-law_ecli ?v BIND("ecli" AS ?k) }\n'
               'UNION { ?r cdm:case-law_declares_void_resource_legal ?w . ?r cdm:resource_legal_id_celex ?v . OPTIONAL { ?r cdm:work_date_document ?d } BIND("void" AS ?k) }\n'
               'UNION { ?r cdm:case-law_declares_void_by_preliminary_ruling_resource_legal ?w . ?r cdm:resource_legal_id_celex ?v . '
               'OPTIONAL { ?r cdm:work_date_document ?d } BIND("void_pr" AS ?k) } }') % vals
    out = {}
    for b in sparql(q):
        d = out.setdefault(b['celex'], {})
        d.setdefault(b['k'], []).append((b.get('v'), b.get('d')) if b['k'].startswith('void') else b.get('v'))
    return out


def eu_item(celex, titles, det, B):
    """Dated Cellar record. Barrier on every work_date_document of the CELEX (twins included). Validity metadata are post-T knowledge
    when the notice was modified on or after T: then only dates before T are served, the end of validity only when before T and no
    voiding ruling is dated on/after T (void ab initio is written after the fact), the current "in force" flag is masked."""
    ecli = (det.get('ecli') or [None])[0]
    tl = [t for _, t in sorted(titles)]
    if not eu_kept(celex) or not law_ok(B, [celex, 'celex:' + celex, ecli], det.get('date') or [None], tl): return None
    date = max(det['date']); lmd = max(det.get('lmd') or [''])
    fresh = bool(lmd) and date_upper(lmd) is not None and date_upper(lmd) < B.T
    voids = [(c, d, k) for k in ('void', 'void_pr') for c, d in det.get(k, [])]
    vb = [{'celex': c, 'date': d[:10], 'by_preliminary_ruling': k == 'void_pr'} for c, d, k in voids if _before(d, B) and c != celex]
    late_void = any(not _before(d, B) for _, d, _ in voids)
    eif = sorted(det.get('eif') or []); eov = sorted(det.get('eov') or [])
    keep = (lambda x: x) if fresh else (lambda x: _before(x, B))
    it = {'id': 'celex:' + celex, 'celex': celex, 'doi': None, 'title': ' '.join(tl[0].replace('#', ' - ').split()) if tl and tl[0] else None, 'year': date[:4], 'date': date[:10],
          'journal': 'EUR-Lex (Cellar)', 'type': 'decision' if celex[0] == '6' else 'text', 'tier': 'primary', 'order': 'EU', 'consolidated': celex[0] == '0',
          'in_force_from': keep(eif[0]) if eif else None, 'applies_from': keep(eif[-1]) if eif else None,   # applies_from: latest entry-into-force value
          'in_force_to': (eov[-1] if fresh else (_before(eov[-1], B) if not late_void else None)) if eov else None,   # inclusive in Cellar
          'in_force': ((det.get('flag') or [None])[0] if fresh else None), 'declared_void_by': vb,
          'validity': 'notice unchanged since before T' if fresh else 'notice modified on/after T: post-T validity masked (only dates before T kept)'}
    if celex[0] == '6':
        it.update(ecli=ecli, court=celex[5:7], set_aside_by=[v['celex'] for v in vb if not v['by_preliminary_ruling']])
    return it


def _eu_words(q):
    return [w for w in re.findall(r'\w+', q.lower()) if len(w) >= 3 and not w.isdigit()][:6]


def search_eurlex(q, n, B):
    """EUR-Lex Cellar SPARQL: title words (EN or FR expression), date of the act/ruling bounded in the query to [start, eve of T].
    Two queries (legislation 0/3, case law 6; otherwise recent rulings bury the acts), interleaved, then one details query."""
    words = _eu_words(q)
    if not words: return [], 'no usable title word (3 letters or more)'
    langs = ', '.join(f'<{EU_LANG}{x}>' for x in ('ENG', 'FRA'))
    order, titles, nrows = {'leg': [], 'cl': []}, {}, {}
    for part, sector in (('leg', '^[03]'), ('cl', '^6')):
        # bif:contains = Virtuoso free-text index on the titles (a CONTAINS(LCASE()) scan times out on the whole of Cellar, measured 2026-10-28)
        sq = CDM + ('SELECT DISTINCT ?celex ?date ?title ?lang WHERE { ?e cdm:expression_title ?title . ?title bif:contains "' + ' AND '.join(f"'{w}'" for w in words) + '" .\n'
                    f'?e cdm:expression_belongs_to_work ?w ; cdm:expression_uses_language ?lang . FILTER(?lang IN ({langs}))\n'
                    f'?w cdm:resource_legal_id_celex ?celex ; cdm:work_date_document ?date . FILTER(?date >= "{B.start}"^^xsd:date && ?date <= "{B.eve}"^^xsd:date)\n'
                    f'FILTER(REGEX(STR(?celex), "{sector}") && !REGEX(STR(?celex), "^6[0-9]{{4}}(CC|[CTF]A)") && !CONTAINS(STR(?celex), "_RES") && !CONTAINS(STR(?celex), "_INF"))\n'
                    '} ORDER BY DESC(?date) LIMIT 100')
        rows = sparql(sq); nrows[part] = len(rows)
        for r in rows:
            c = r['celex']
            if c not in titles: order[part].append(c); titles[c] = []
            titles[c].append((0 if r.get('lang', '').endswith('ENG') else 1, r.get('title')))
    k = max(n, 20)
    mix = [c for pair in zip(order['leg'][:k], order['cl'][:k]) for c in pair]
    mix = (mix + order['leg'][len(mix) // 2:k] + order['cl'][len(mix) // 2:k])[:k]
    det = eu_details(mix)
    out = [x for x in (eu_item(c, titles[c], det.get(c, {}), B) for c in mix) if x]
    return out[:n], (f"bounded: legislation {len(order['leg'])} CELEX ({nrows['leg']} title rows), case law {len(order['cl'])} CELEX ({nrows['cl']} rows); "
                     'LIMIT 100 each, most recent first; Cellar gives no count')


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


def read_celex(celex, B):
    """CELEX notice (dates, validity under the barrier) + start of the official text through Cellar content negotiation (XHTML, EN then FR);
    for a judgment longer than TEXT_HEAD, its operative part is appended (head_and_operative).
    EUR-Lex HTML (eur-lex.europa.eu) answers 202 with an empty body (bot challenge): not used (ACCESS-POLICY.md)."""
    if not re.fullmatch(CELEX_FORM, celex): return {'refusal': 'malformed CELEX'}
    if re.match(r'^6\d{4}CC', celex): return {'refusal': 'Advocate General opinion: excluded (law.non_binding, leakage risk)'}
    rows = sparql(CDM + 'SELECT DISTINCT ?title ?lang WHERE { ?w cdm:resource_legal_id_celex "%s"^^xsd:string . ?e cdm:expression_belongs_to_work ?w ; '
                  'cdm:expression_uses_language ?lang ; cdm:expression_title ?title . FILTER(?lang IN (<%sENG>, <%sFRA>)) }' % (celex, EU_LANG, EU_LANG))
    det = eu_details([celex]).get(celex)
    if not det: return {'refusal': 'not found'}
    it = eu_item(celex, [(0 if r.get('lang', '').endswith('ENG') else 1, r.get('title')) for r in rows], det, B)
    if not it: return {'refusal': 'after T, forbidden or excluded'}
    for lang in ('eng', 'fra'):
        try: x = fetch('https://publications.europa.eu/resource/celex/' + urllib.parse.quote(celex), headers={'Accept': 'application/xhtml+xml, text/html;q=0.9', 'Accept-Language': lang})
        except Exception: continue
        t = html.unescape(re.sub(r'<[^>]+>', ' ', re.sub(r'(?is)<(head|script|style)\b.*?</\1>', ' ', x.decode('utf-8', 'replace'))))
        t = ' '.join(t.split())
        if t:
            t, how = head_and_operative(t, celex[0] == '6')
            return dict(it, abstract=t, text_language=lang, text_source=f'Cellar (official text, {how})')
    return dict(it, abstract='(no text available from Cellar)')


def read_ecli_eu(ecli, B):
    if not re.fullmatch(r'ECLI:EU:[A-Z]{1,2}:\d{4}:[0-9A-Z.]{1,12}', ecli): return {'refusal': 'malformed EU ECLI (expected ECLI:EU:C:2014:238)'}
    rows = sparql(CDM + 'SELECT DISTINCT ?celex WHERE { ?w cdm:case-law_ecli "%s"^^xsd:string ; cdm:resource_legal_id_celex ?celex }' % ecli)
    cs = sorted({r['celex'] for r in rows if eu_kept(r['celex'])})
    return read_celex(cs[0], B) if cs else {'refusal': 'not found (or Advocate General opinion, excluded)'}


JA = 'https://opendata.justice-administrative.fr/recherche/api/'
JA_COVERAGE = {'CE': '2021-09-30', 'CAA': '2022-03-31', 'TA': '2022-06-30'}   # law.md 4: opening of the open data per court level
JA_NULL = ('', 'undefined', 'null', 'none')


def ja_cov(code): return next((v for k, v in JA_COVERAGE.items() if (code or '').startswith(k)), None)


def ja_item(h, B):
    s = h.get('_source') or {}
    code, ident = s.get('Code_Juridiction') or '', (s.get('Identification') or '').removesuffix('.xml')
    ecli = None if str(s.get('Numero_ECLI') or '').strip().lower() in JA_NULL else s['Numero_ECLI']   # literal "undefined" removed
    if not code or not ident: return None
    # decision date AND upload date to the open data (lastModified) < T
    if not law_ok(B, [ecli, s.get('Numero_Dossier'), f'ja:{code}/{ident}'], [s.get('Date_Lecture'), s.get('lastModified')]): return None
    return {'id': f'ja:{code}/{ident}', 'ecli': ecli, 'doi': None, 'number': s.get('Numero_Dossier'),
            'title': f"{s.get('Nom_Juridiction')}, {s.get('Type_Decision') or 'decision'} n° {s.get('Numero_Dossier')}, {s.get('Date_Lecture')}",
            'year': (s.get('Date_Lecture') or '')[:4], 'date': s.get('Date_Lecture'), 'date_published': s.get('lastModified'),
            'journal': 'opendata.justice-administrative.fr', 'court': code, 'court_name': s.get('Nom_Juridiction'), 'formation': s.get('Formation_Jugement'),
            'publication': s.get('Code_Publication') or None, 'type': 'decision', 'tier': 'primary', 'order': 'FR-ADM', 'coverage_from': ja_cov(code)}


def _ja_hits(r): return ((r.get('decisions') or {}).get('body') or {}).get('hits') or {}


JA_COURT = r'CE|CAA\d{2}|TA\d{2,3}'   # exact court code (probe 2026-10-28: "TA" or "CAA" alone match nothing)


def search_justice_administrative(q, n, B, court=None, date_from=None, date_to=None):
    """Administrative courts open data (level 2 `page`): JSON back end of the public engine, decision date bounded on the provider side
    (model_searchANDdates, Date_Lecture range ending on the eve of T); several words = OR, exact phrase in quotes, numbers work.
    The provider has no relevance order (no score; probe 2026-10-28): results come sorted by date, most recent first. To narrow:
    court (exact code, model_search_date_juri route), date_from / date_to (decision-date window, kept inside [start, eve of T])."""
    qq = ' '.join(q.replace('/', ' ').split())
    if not qq: return [], 'empty query'
    if court and not re.fullmatch(JA_COURT, court): return [], f'court: exact code expected ({JA_COURT}, e.g. CE, TA75, CAA69)'
    lo, hi = B.start, B.eve
    for v, side in ((date_from, 'from'), (date_to, 'to')):
        if v is None: continue
        try: d = dt.date.fromisoformat(v)
        except (TypeError, ValueError): return [], f'{side}: date YYYY-MM-DD expected'
        if side == 'from': lo = max(lo, d)
        else: hi = min(hi, d)
    if lo > hi: return [], f'empty window ({lo} > {hi}; the end is at most the eve of T)'
    route = f'model_search_date_juri/openData/Date_Lecture/{urllib.parse.quote(qq, safe="")}/{court}' if court else f'model_searchANDdates/openData/Date_Lecture/{urllib.parse.quote(qq, safe="")}'
    h = _ja_hits(jget(f'{JA}{route}/{lo}/{hi}/100'))
    out = [x for x in (ja_item(i, B) for i in h.get('hits') or []) if x]
    tot = (h.get('total') or {}).get('value') if isinstance(h.get('total'), dict) else h.get('total')
    cov = ', '.join(f'{k} {v}' for k, v in JA_COVERAGE.items())
    return out[:n], (f'bounded: provider announces {tot} (false totals, capped at 1,000, 100 per call); sorted by date, most recent first (no relevance order): '
                     f'search a known decision by its number or an exact phrase in quotes, or narrow with --court / --from / --to; window {lo} to {hi}'
                     f'{", court " + court if court else ""}; coverage_from {cov}')


def read_ja(ident, B):
    m = re.fullmatch(r'([A-Z]{2,3}\d{0,3})/([A-Z]{2,5}_[A-Za-z0-9]+_\d{8})', ident)
    if not m: return {'refusal': 'expected form ja:<court code>/<file>, e.g. ja:CE/DCE_515092_20261027'}
    hits = _ja_hits(jget(f'{JA}elastic/decisions/{m.group(1)}/{m.group(2)}')).get('hits') or []
    hit = next((x for x in hits if (x.get('_source') or {}).get('Identification', '').removesuffix('.xml') == m.group(2)), None)
    if not hit: return {'refusal': 'not found'}
    it = ja_item(hit, B)
    if not it: return {'refusal': 'after T or forbidden'}
    return dict(it, abstract=str(hit['_source'].get('paragraph') or '(no text available)').replace('$$$', '\n')[:20000])


def read_ecli_fr(ecli, B):
    m = re.fullmatch(r'ECLI:FR:[A-Z]+:\d{4}:([0-9A-Z]+)\.\d{8}', ecli)
    if not m: return {'refusal': 'not an administrative-court ECLI (judicial ECLI: search-judilibre by the appeal number, then read judilibre:<id>)'}
    hits = _ja_hits(jget(f'{JA}Simple_Search/openData/{urllib.parse.quote(m.group(1))}/100')).get('hits') or []
    hit = next((x for x in hits if (x.get('_source') or {}).get('Numero_ECLI') == ecli), None)
    if not hit: return {'refusal': 'not found'}
    return read_ja(f"{hit['_source']['Code_Juridiction']}/{hit['_source']['Identification'].removesuffix('.xml')}", B)


HAL = 'https://api.archives-ouvertes.fr/search/'
HAL_FL = 'halId_s,title_s,producedDate_s,submittedDate_s,doiId_s,uri_s,docType_s,authFullName_s'


def hal_item(d, B, with_abstract=False):
    title = (d.get('title_s') or [None])[0]
    # production date AND deposit date < T (a 2018 work deposited in 2020 is refused for T in 2019)
    if not law_ok(B, [d.get('doiId_s'), d.get('halId_s'), 'hal:' + str(d.get('halId_s'))], [d.get('producedDate_s'), d.get('submittedDate_s')], d.get('title_s') or []): return None
    it = {'id': 'hal:' + d['halId_s'], 'hal': d['halId_s'], 'doi': d.get('doiId_s'), 'title': title, 'year': (d.get('producedDate_s') or '')[:4],
          'date': d.get('producedDate_s'), 'date_deposited': (d.get('submittedDate_s') or '')[:10], 'journal': 'HAL (law)',
          'first_author': (d.get('authFullName_s') or [None])[0], 'type': d.get('docType_s'), 'url': d.get('uri_s'), 'tier': 'secondary', 'order': None}
    if with_abstract: it['abstract'] = ' '.join(' '.join(d.get('abstract_s') or ['(no abstract available)']).split())[:6000]
    return it


def search_hal(q, n, B):
    """HAL, law domain (level1_domain_s:shs.droit; domain_s returns 0): production and deposit dates bounded on the server to the eve of T."""
    rng = f'[{B.start}T00:00:00Z TO {B.eve}T23:59:59Z]'
    r = jget(HAL + '?' + urllib.parse.urlencode([('q', q or '*:*'), ('fq', 'level1_domain_s:shs.droit'), ('fq', 'producedDate_tdate:' + rng),
                                                 ('fq', 'submittedDate_tdate:' + rng), ('wt', 'json'), ('fl', HAL_FL), ('rows', n)]))['response']
    return [x for x in (hal_item(d, B) for d in r.get('docs', [])) if x], r.get('numFound')


def read_hal(hid, B):
    if not re.fullmatch(r'[a-z]+-\d+', hid): return {'refusal': 'expected form hal:<halId>, e.g. hal:hal-01891420'}
    docs = jget(HAL + '?' + urllib.parse.urlencode([('q', f'halId_s:{hid}'), ('wt', 'json'), ('fl', HAL_FL + ',abstract_s'), ('rows', 1)]))['response'].get('docs', [])
    if not docs: return {'refusal': 'not found'}
    return hal_item(docs[0], B, with_abstract=True) or {'refusal': 'after T or forbidden'}


THESES = 'https://theses.fr/api/v1/theses/'


def dmy(s):
    """theses.fr dd/mm/yyyy -> ISO (a lone year stays a year: no precision is fabricated)."""
    m = re.fullmatch(r'\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*', str(s or ''))
    if m: return f'{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}'
    m = re.fullmatch(r'\s*(\d{4})(-\d{2}(-\d{2})?)?\s*', str(s or ''))
    return m.group(0).strip() if m else None


def theses_item(t, B, with_abstract=False):
    nnt = t.get('nnt') or t.get('id'); d = dmy(t.get('dateSoutenance'))
    titles = [t.get('titrePrincipal'), t.get('titreEN')] + list((t.get('titres') or {}).values())
    if not nnt or not law_ok(B, [t.get('doi'), nnt, 'thesesfr:' + str(nnt)], [d], titles): return None   # defence date < T; not defended -> no date -> refused
    a = (t.get('auteurs') or [{}])[0]
    it = {'id': 'thesesfr:' + nnt, 'nnt': nnt, 'doi': t.get('doi'), 'title': t.get('titrePrincipal'), 'year': d[:4], 'date': d,
          'journal': 'theses.fr' + (f" ({t['etabSoutenanceN']})" if t.get('etabSoutenanceN') else ''), 'first_author': ' '.join(x for x in (a.get('prenom'), a.get('nom')) if x) or None,
          'type': 'thesis', 'discipline': t.get('discipline'), 'tier': 'secondary', 'order': None}
    if with_abstract:
        r = t.get('resumes') or {}
        it['abstract'] = ' '.join(str(r.get('fr') or r.get('en') or '(no abstract available)').split())[:6000]
    return it


def search_theses_fr(q, n, B):
    """theses.fr API v1 (ABES): defence date bounded on the provider side, dateSoutenance:[start TO eve of T]."""
    qq = f'({q or "*"}) AND dateSoutenance:[{B.start} TO {B.eve}]'
    r = jget(THESES + 'recherche/?' + urllib.parse.urlencode({'q': qq, 'nombre': n}))
    return [x for x in (theses_item(t, B) for t in r.get('theses', [])) if x], r.get('totalHits')


def read_theses_fr(nnt, B):
    if not re.fullmatch(r'[0-9]{4}[A-Z0-9]{4,12}', nnt): return {'refusal': 'expected form thesesfr:<nnt>, e.g. thesesfr:2018LIMO0025'}
    try: t = jget(THESES + 'these/' + nnt)
    except urllib.error.HTTPError as e:
        if e.code in (400, 404): return {'refusal': 'not found'}
        raise
    return theses_item(dict(t, nnt=t.get('nnt') or nnt), B, with_abstract=True) or {'refusal': 'after T, forbidden or not defended'}


LAW_PREFIX = ('celex:', 'ecli:', 'ja:', 'hal:', 'thesesfr:')


def read_law(ident, B):
    p, _, v = ident.partition(':'); p = p.lower() + ':'; v = v.strip()
    if p == 'celex:': return read_celex(v, B)
    if p == 'ecli:':
        v = v if v.upper().startswith('ECLI:') else 'ECLI:' + v
        if v.upper().startswith('ECLI:EU:'): return read_ecli_eu(v, B)
        if v.upper().startswith('ECLI:FR:'): return read_ecli_fr(v, B)
        return {'refusal': 'ECLI of an order not served (ECHR: HUDOC not wired)'}
    if p == 'ja:': return read_ja(v, B)
    if p == 'hal:': return read_hal(v, B)
    return read_theses_fr(v, B)


ENGINES = {'pubmed': search_pubmed, 'europepmc': search_europepmc, 'crossref': search_crossref, 'openalex': search_openalex, 'arxiv': search_arxiv,
           'eurlex': search_eurlex, 'justice-administrative': search_justice_administrative, 'hal': search_hal, 'theses-fr': search_theses_fr}
CODE_ENGINES = {'search-code': 'code', 'versions': 'versions', 'paper-code': 'paper-code', 'provenance': 'provenance'}  # command -> engine ; never served without plugin
VERSION_FORM = r'(pypi|npm|cargo):(@?[A-Za-z0-9][\w.+-]*(?:/[A-Za-z0-9][\w.+-]*)?)@([A-Za-z0-9][\w.+-]*)'          # package (npm @scope/name allowed) @ version
VERSION_FORM_MSG = 'expected form <pypi|npm|cargo>:<package>@<version>'
ORIGIN_FORM_MSG = 'expected form <origin https://... | swh:1:...>'


def read(ident, B):
    ident = ident.strip()
    if ident.lower().startswith('arxiv:'):
        return read_arxiv(ident, B)
    if ident.lower().startswith(LAW_PREFIX): return read_law(ident, B)
    if ident.lower().startswith(EXTRA_PREFIX): return read_extra(ident, B)
    if ident.upper().startswith('ECLI:'): return read_law('ecli:' + ident, B)
    if ident.lower().startswith(B3_PREFIX): return read_b3(ident, B)
    if ident.lower().startswith('pmid:') or ident.isdigit():
        pmid = ident.split(':')[-1]
        meta = pubmed_summ([pmid], B)
        if not meta: return {'refusal': 'after T, forbidden or not found'}
        x = fetch(f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&rettype=abstract&retmode=text' + ncbi_key()).decode('utf-8', 'replace')
        return dict(meta[0], abstract=x[:6000])
    doi = ident[4:] if ident.lower().startswith('doi:') else ident
    r = jget('https://www.ebi.ac.uk/europepmc/webservices/rest/search?format=json&resultType=core&pageSize=1&query=' + urllib.parse.quote(f'DOI:"{doi}"'))
    res = r.get('resultList', {}).get('result', [])
    if res and res[0].get('abstractText'):
        it = epmc_item(res[0], B)
        if not it: return {'refusal': 'after T or forbidden'}
        return dict(it, abstract=re.sub('<[^>]+>', ' ', res[0]['abstractText'])[:6000])
    try: w = oa_work('doi:' + doi)
    except Exception:
        try: m = jget('https://api.crossref.org/works/' + urllib.parse.quote(doi) + _mailto('?'))['message']
        except Exception: return {'refusal': 'not found'}
        it = cr_item(m, B)
        if not it: return {'refusal': 'after T, forbidden or not found'}
        return dict(it, abstract=re.sub('<[^>]+>', ' ', m.get('abstract') or '(no abstract available)')[:6000])
    it = oa_item(w, B)
    if not it or not crossref_deposit([it], B): return {'refusal': 'after T, forbidden or deposit not attested'}
    inv = w.get('abstract_inverted_index') or {}
    pos = sorted((p, word) for word, ps in inv.items() for p in ps)
    return dict(it, abstract=' '.join(m for _, m in pos)[:6000] or '(no abstract available)')


EPMC = 'https://www.ebi.ac.uk/europepmc/webservices/rest/'


def epmc_resolve(ident, B):
    """-> (source, id, dated item) via Europe PMC; None when absent; refused when after T."""
    ident = ident.strip()
    q = f'EXT_ID:{ident.split(":")[-1]} AND SRC:MED' if ident.lower().startswith('pmid:') or ident.isdigit() else f'DOI:"{ident[4:] if ident.lower().startswith("doi:") else ident}"'
    res = jget(EPMC + 'search?format=json&resultType=lite&pageSize=1&query=' + urllib.parse.quote(q)).get('resultList', {}).get('result', [])
    if not res: return None
    return res[0]['source'], res[0]['id'], epmc_item(res[0], B)


def epmc_date(ids, B):
    """Batch recheck (indexing AND publication date < T) of MED identifiers."""
    out = []
    for i in range(0, min(len(ids), 200), 50):
        q = '(' + ' OR '.join(f'EXT_ID:{x}' for x in ids[i:i + 50]) + f') AND SRC:MED AND FIRST_IDATE:[1800-01-01 TO {B.eve}]'
        r = jget(EPMC + 'search?format=json&resultType=lite&pageSize=100&query=' + urllib.parse.quote(q))
        out += [x for x in (epmc_item(v, B) for v in r.get('resultList', {}).get('result', [])) if x]
    return out


def crossref_batch(dois, B):
    """Dated Crossref notices (deposit AND publication < T) for a list of DOIs, in batches."""
    out = []
    for i in range(0, min(len(dois), 300), 40):
        f = ','.join('doi:' + x for x in dois[i:i + 40])
        m = jget('https://api.crossref.org/works?rows=100&select=DOI,title,issued,created,container-title,author,type&filter=' + urllib.parse.quote(f, safe=':,') + _mailto())['message']
        out += [x for x in (cr_item(it, B) for it in m.get('items', [])) if x]
    return out


def doi_of(ident, B):
    if ident.lower().startswith('doi:'): return ident[4:]
    r = epmc_resolve(ident, B)
    if r:
        res = jget(EPMC + 'search?format=json&resultType=lite&pageSize=1&query=' + urllib.parse.quote(f'EXT_ID:{r[1]} AND SRC:{r[0]}')).get('resultList', {}).get('result', [])
        return (res[0].get('doi') if res else None)
    return None


def _arxiv_ok(ident, B):
    """An arXiv identifier goes to OpenAlex chaining only when its "published" (v1) is before T."""
    return 'refusal' not in read_arxiv(ident, B)


def citing(ident, n, B):
    if ident.strip().lower().startswith(EXTRA_PREFIX): return [], 'citation chaining not served for nct:, dblp:, econbiz:, osv: identifiers (read the DOI)'
    if ident.strip().lower().startswith(LAW_PREFIX): return [], 'citation chaining not served for law identifiers (Cellar work_cites_work: not wired)'
    if ident.lower().startswith('arxiv:'):
        if not _arxiv_ok(ident, B): return [], 'document after T or forbidden'
        w = oa_work(ident)
        return search_openalex('', n, B, ',cites:' + w['id'].rsplit('/', 1)[-1])
    r = epmc_resolve(ident, B)
    if r and r[2]:
        cit = jget(EPMC + f'{r[0]}/{r[1]}/citations?format=json&pageSize=1000').get('citationList', {}).get('citation', [])
        ids = [c['id'] for c in cit if c.get('source') == 'MED' and str(c.get('pubYear') or '9999') <= str(B.T.year)]
        B.excluded += len(cit) - len(ids)
        out = epmc_date(ids, B)
        if out or cit: return out[:n], f'{len(cit)} citing in Europe PMC (all dates), {len(out)} before T'
    if r and not r[2]: return [], 'document after T or forbidden'
    doi = doi_of(ident, B)
    if doi:
        if not crossref_batch([doi], B): return [], 'document after T, forbidden or deposit not attested'
        try:
            cit = jget('https://api.opencitations.net/index/v2/citations/doi:' + doi)
            dois = [t[4:] for c in cit if str(c.get('creation') or '9999') < str(B.T) for t in c.get('citing', '').split() if t.startswith('doi:')]
            B.excluded += len(cit) - len(dois)
            out = crossref_batch(dois, B)
            if out or cit: return out[:n], f'{len(cit)} citing in OpenCitations (all dates), {len(out)} before T (Crossref recheck)'
        except Exception: pass
    w = oa_work(ident)
    return search_openalex('', n, B, ',cites:' + w['id'].rsplit('/', 1)[-1])


def references(ident, n, B):
    if ident.strip().lower().startswith(EXTRA_PREFIX): return [], 'citation chaining not served for nct:, dblp:, econbiz:, osv: identifiers (read the DOI)'
    if ident.strip().lower().startswith(LAW_PREFIX): return [], 'citation chaining not served for law identifiers (Cellar work_cites_work: not wired)'
    if ident.lower().startswith('arxiv:'):
        if not _arxiv_ok(ident, B): return [], 'document after T or forbidden'
        return _references_openalex(oa_work(ident), n, B)
    r = epmc_resolve(ident, B)
    if r and not r[2]: return [], 'document after T or forbidden'
    if r:
        refs = jget(EPMC + f'{r[0]}/{r[1]}/references?format=json&pageSize=1000').get('referenceList', {}).get('reference', [])
        med = [x['id'] for x in refs if x.get('source') == 'MED' and x.get('id')]
        out = epmc_date(med, B) if med else []
        for x in refs:
            if x.get('source') == 'MED' and x.get('id'): continue
            # without PMID: year strictly before the year of T (strict), forbidden titles filtered
            if not B.ok(x.get('doi'), year_before_T(x.get('pubYear'), B), title=x.get('title')): continue
            out.append({'id': f"doi:{x['doi']}" if x.get('doi') else 'no-id', 'title': x.get('title'), 'year': x.get('pubYear'), 'journal': x.get('journalAbbreviation'), 'first_author': (x.get('authorString') or '').split(',')[0]})
        if out: return out, len(refs)
    doi = doi_of(ident, B)
    if doi:
        try: m = jget('https://api.crossref.org/works/' + urllib.parse.quote(doi) + _mailto('?'))['message']
        except Exception: m = None
        if m is not None:
            if not cr_item(m, B): return [], 'document after T, forbidden or deposit not attested'
            refs = m.get('reference', [])
            out = crossref_batch([x['DOI'] for x in refs if x.get('DOI')], B)
            for x in refs:
                if x.get('DOI'): continue
                t = x.get('article-title') or x.get('unstructured') or x.get('volume-title')
                if t and B.ok(None, year_before_T(x.get('year'), B), title=t):
                    out.append({'id': 'no-id', 'title': t[:300], 'year': x.get('year'), 'first_author': x.get('author')})
            if out: return out, len(refs)
    w = oa_work(ident)
    if not oa_item(w, B): return [], 0
    return _references_openalex(w, n, B)


def _references_openalex(w, n, B):
    rr = [x.rsplit('/', 1)[-1] for x in w.get('referenced_works', [])][:100]
    out = []
    for i in range(0, len(rr), 50):
        v = jget(f'https://api.openalex.org/works?per_page=50&select={OASEL}&filter=openalex_id:' + '|'.join(rr[i:i + 50]) + oa_key())
        out += [x for x in (oa_item(y, B) for y in v.get('results', [])) if x]
    return crossref_deposit(out, B), len(rr)


# ---------------------------------------------------------------- extra keyless engines (v0.3.1): clinicaltrials (biology), dblp (cs-ai), econbiz (finance), osv (code)

INTERVAL.update({'clinicaltrials.gov': 1.0, 'sparql.dblp.org': 2.0, 'api.econbiz.de': 1.0})
STOP.update({'clinicaltrials.gov': (429,), 'sparql.dblp.org': (403, 429, 'timeout'), 'api.econbiz.de': (429,)})
EXTRA_PREFIX = ('nct:', 'dblp:', 'econbiz:', 'osv:')


def extra_ok(B, ids, dates, titles=()):
    """Barrier of the extra engines: forbidden identifiers (same list as the DOIs) and titles, then every date < T through B.ok."""
    if any(i and str(i).lower().replace('https://doi.org/', '') in B.forbidden for i in ids) or \
       any(t and any(title_sim(tokens(t), f) >= CFG['review_title_threshold'] for f in B.titles) for t in titles):
        B.excluded += 1; return False
    return B.ok(None, *dates)


def doi_recheck(items, B):
    """Items carrying a DOI pass only when Crossref attests deposit AND publication < T (crossref_deposit, strict); the others are kept."""
    withd = [x for x in items if x.get('doi')]
    ok = {x['id'][4:].lower() for x in crossref_deposit([{'id': 'doi:' + x['doi']} for x in withd], B)} if withd else set()
    return [x for x in items if not x.get('doi') or x['doi'].lower() in ok]


CTGOV = 'https://clinicaltrials.gov/api/v2/studies'
CT_FIELDS = ('protocolSection.identificationModule,protocolSection.statusModule,protocolSection.conditionsModule,protocolSection.designModule,'
             'protocolSection.sponsorCollaboratorsModule,hasResults')


def ct_item(s, B, with_text=False):
    """ClinicalTrials.gov study. First submitted AND first posted < T. A record updated on/after T: status, phase, enrollment, start date
    and texts are post-T knowledge -> masked; results only when first posted < T; no date on/after T is ever served."""
    ps = s.get('protocolSection') or {}; idm = ps.get('identificationModule') or {}; st = ps.get('statusModule') or {}; de = ps.get('designModule') or {}
    nct = idm.get('nctId'); d = lambda k: (st.get(k) or {}).get('date')
    if not nct or not extra_ok(B, [nct, 'nct:' + nct], [st.get('studyFirstSubmitDate'), d('studyFirstPostDateStruct')], [idm.get('briefTitle'), idm.get('officialTitle')]):
        return None
    fresh = bool(_before(d('lastUpdatePostDateStruct'), B))
    res = _before(d('resultsFirstPostDateStruct'), B)
    keep = (lambda x: x) if fresh else (lambda x: None)
    it = {'id': 'nct:' + nct, 'nct': nct, 'doi': None, 'title': idm.get('briefTitle'), 'year': (d('studyFirstPostDateStruct') or '')[:4],
          'date': d('studyFirstPostDateStruct'), 'date_submitted': st.get('studyFirstSubmitDate'), 'journal': 'ClinicalTrials.gov',
          'sponsor': ((ps.get('sponsorCollaboratorsModule') or {}).get('leadSponsor') or {}).get('name'), 'study_type': de.get('studyType'),
          'conditions': (ps.get('conditionsModule') or {}).get('conditions'), 'status': keep(st.get('overallStatus')), 'phase': keep(de.get('phases')),
          'enrollment': keep((de.get('enrollmentInfo') or {}).get('count')), 'start_date': keep(_before(d('startDateStruct'), B)),   # a planned start on/after T: not served
          'has_results': bool(res and s.get('hasResults', True)), 'date_results_posted': res, 'date_last_update': keep(d('lastUpdatePostDateStruct')),
          'type': 'trial registration', 'validity': 'record unchanged since before T' if fresh else 'record updated on/after T: status, phase, enrollment, start date and texts masked'}
    if with_text:
        ds = ps.get('descriptionModule') or {}; om = ps.get('outcomesModule') or {}
        out = lambda k: [{'measure': o.get('measure'), 'time_frame': o.get('timeFrame')} for o in om.get(k) or []]
        it.update(official_title=idm.get('officialTitle'), abstract=keep(ds.get('briefSummary')) or '(masked: record updated on/after T)',
                  primary_outcomes=keep(out('primaryOutcomes')), secondary_outcomes=keep(out('secondaryOutcomes')),
                  interventions=keep([{'type': i.get('type'), 'name': i.get('name')} for i in (ps.get('armsInterventionsModule') or {}).get('interventions') or []]))
    return it


def search_clinicaltrials(q, n, B):
    """ClinicalTrials.gov API v2 (keyless): first-posted date bounded on the provider side, AREA[StudyFirstPostDate]RANGE[start, eve of T]."""
    lo = B.start.isoformat() if B.since else 'MIN'
    r = jget(CTGOV + '?' + urllib.parse.urlencode({'query.term': q, 'filter.advanced': f'AREA[StudyFirstPostDate]RANGE[{lo},{B.eve}]', 'pageSize': n,
                                                    'countTotal': 'true', 'fields': CT_FIELDS}))
    return [x for x in (ct_item(s, B) for s in r.get('studies', [])) if x], r.get('totalCount')


def read_nct(nct, B):
    if not re.fullmatch(r'NCT\d{8}', nct.upper()): return {'refusal': 'expected form nct:NCT01234567'}
    try: s = jget(CTGOV + '/' + nct.upper())
    except urllib.error.HTTPError as e:
        if e.code == 404: return {'refusal': 'not found'}
        raise
    return ct_item(s, B, with_text=True) or {'refusal': 'after T or forbidden'}


DBLP_SPARQL = 'https://sparql.dblp.org/sparql'
DBLP_PRE = ('PREFIX dblp: <https://dblp.org/rdf/schema#>\nPREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\nPREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n'
            'PREFIX ql: <http://qlever.cs.uni-freiburg.de/builtin-functions/>\n')


def dblp_rows(q):
    """dblp SPARQL (QLever, keyless). The search API dblp.org/search answers an Anubis anti-robot page (HTTP 202): not used (ACCESS-POLICY.md).
    429 -> rate_limited with the Retry-After asked (no retry); a non-JSON answer -> bot_challenge, never an empty result."""
    url = DBLP_SPARQL + '?' + urllib.parse.urlencode({'query': q})
    try: raw = fetch(url, headers={'Accept': 'application/sparql-results+json'})
    except urllib.error.HTTPError as e:
        if e.code == 429 and b'timed out' in (e.read() or b'')[:400]: raise ProviderError('provider_error: dblp query timed out on the server (not an empty result)')
        if e.code == 429: raise ProviderError(f"rate_limited: dblp asks to wait {e.headers.get('Retry-After') or 'unspecified'} s (no retry)")
        raise
    try: r = json.loads(raw)
    except ValueError:                                                  # an anti-robot page is never kept in the cache as an answer
        (STATE / 'cache' / hashlib.sha256((url + json.dumps({'Accept': 'application/sparql-results+json'}, sort_keys=True)).encode()).hexdigest()).unlink(missing_ok=True)
        raise ProviderError('bot_challenge: dblp answered a non-JSON page (not an empty result)')
    return [{k: v.get('value') for k, v in b.items()} for b in r.get('results', {}).get('bindings', [])]


def arxiv_month(aid):
    """YYYY-MM of the first submission encoded in an arXiv identifier (2401.01234 -> 2024-01; cs/0101001 -> 2001-01), else None."""
    m = re.match(r'(?:[a-z-]+(?:\.[A-Z]{2})?/)?(\d{2})(\d{2})[.\d]', aid or '')
    return f"{(19 if int(m.group(1)) > 90 else 20)}{m.group(1)}-{m.group(2)}" if m else None


def dblp_items(rows, B, limit=100):
    """Rows grouped per record. dblp has only years: every year (publication, event) strictly before the year of T (year_before_T);
    a CoRR record is dated by its arXiv identifier (month of v1 < T); any other DOI is rechecked on Crossref (doi_recheck)."""
    recs = {}
    for r in rows:
        x = recs.setdefault(r['p'], {'years': set(), 'doi': None, 'venue': None, 'title': r.get('title'), 'label': r.get('label')})
        x['years'] |= {r[k] for k in ('year', 'ev') if r.get(k)}
        x['doi'] = x['doi'] or (r.get('doi') or '').replace('https://doi.org/', '') or None; x['venue'] = x['venue'] or r.get('venue')
    out = []
    for p, x in recs.items():
        key_ = p.removeprefix('https://dblp.org/rec/'); doi = x['doi']
        ax = re.match(r'(?i)10\.48550/arxiv\.(.+)', doi or '')
        dates = [arxiv_month(ax.group(1))] if ax else [year_before_T(y, B) for y in sorted(x['years'])]
        if not extra_ok(B, [doi, key_, 'dblp:' + key_], dates or [None], [x['title']]): continue
        out.append({'id': f'arxiv:{ax.group(1)}' if ax else f'doi:{doi}' if doi else f'dblp:{key_}', 'dblp': key_, 'doi': None if ax else doi,
                    'title': x['title'], 'year': max(x['years']) if x['years'] else None, 'journal': x['venue'], 'type': 'publication',
                    'first_author': (x['label'] or '').split(':', 1)[0].split(',')[0].removesuffix(' et al.') or None})
    return doi_recheck(out[:limit], B)                                  # Crossref recheck bounded to the head of the list (calls)


DBLP_SELECT = 'SELECT ?p ?title ?year ?ev ?doi ?venue ?label WHERE { ?p dblp:title ?title ; dblp:yearOfPublication ?year .\n'
DBLP_OPT = 'OPTIONAL { ?p dblp:yearOfEvent ?ev } OPTIONAL { ?p dblp:doi ?doi } OPTIONAL { ?p dblp:publishedIn ?venue } OPTIONAL { ?p rdfs:label ?label }\n'


def search_dblp(q, n, B):
    """dblp through its SPARQL endpoint (QLever title word index ql:contains-word: every word of 3 letters or more, at most 6, `word*` = prefix;
    a CONTAINS(LCASE()) scan with ORDER BY takes 14-25 s, measured 2026-10-28); year bounded on the provider side (year < year of T);
    most recent first, LIMIT 100 rows, grouped and rechecked locally."""
    words = [w for w in re.findall(r'\w+\*?', q.lower()) if len(w.rstrip('*')) >= 3][:6]
    if not words: return [], 'no usable title word (3 letters or more)'
    since = f' && ?year >= "{B.since}"^^xsd:gYear' if B.since else ''
    sq = (DBLP_PRE + DBLP_SELECT + '?t ql:contains-entity ?title . ' + ' '.join(f'?t ql:contains-word "{w}" .' for w in words)
          + f'\nFILTER(?year < "{B.T.year}"^^xsd:gYear{since})\n' + DBLP_OPT + '} ORDER BY DESC(?year) LIMIT 100')
    rows = dblp_rows(sq)
    return dblp_items(rows, B, 2 * n)[:n], f'bounded: {len(rows)} rows (LIMIT 100, most recent year first); dblp gives no count nor relevance'


def read_dblp(key_, B):
    if not re.fullmatch(r'[a-z]+(/[\w.+-]+){1,4}', key_): return {'refusal': 'expected form dblp:<record key>, e.g. dblp:conf/acl/Xiong0LZ24'}
    p = f'<https://dblp.org/rec/{key_}>'
    rows = dblp_rows(DBLP_PRE + f'SELECT ?title ?year ?ev ?doi ?venue ?label WHERE {{ {p} dblp:title ?title ; dblp:yearOfPublication ?year .\n' + DBLP_OPT.replace('?p ', p + ' ') + '}')
    items = dblp_items([dict(r, p='https://dblp.org/rec/' + key_) for r in rows], B)
    return dict(items[0], abstract='(dblp holds no abstract: read the DOI or arXiv identifier)') if items else {'refusal': 'not found, after T, forbidden or deposit not attested'}


ECONBIZ = 'https://api.econbiz.de/v1/'
MONTHS = {m: i + 1 for i, ms in enumerate(('jan january januar', 'feb february februar', 'mar march märz marz', 'apr april', 'may mai', 'jun june juni',
                                            'jul july juli', 'aug august', 'sep sept september', 'oct okt october oktober', 'nov november', 'dec dez december dezember'))
          for m in ms.split()}   # English and German month names (EconBiz records both), whole words only


def econbiz_date(s):
    """EconBiz free-text date -> partial ISO (latest date of an interval): '2018-08-03', '6 May 2026', '27. April 2017', 'January 2026',
    '1st quarter 2026', '[2015]' -> '2015'. No precision is fabricated; None when no year."""
    s = str(s or '')
    iso = re.findall(r'(\d{4})-(\d{2})(?:-(\d{2}))?', s)
    if iso: return max('-'.join(x for x in t if x) for t in iso)
    y = re.findall(r'(?<!\d)(1[5-9]\d{2}|20\d{2})(?!\d)', s)
    if not y: return None
    q = re.search(r'(\d)\s*(?:st|nd|rd|th)?\.?\s*(?:quarter|quartal)', s, re.I)
    m = next((MONTHS[w.lower()] for w in re.findall(r'[A-Za-zä]+', s) if w.lower() in MONTHS), None) or (int(q.group(1)) * 3 if q and 1 <= int(q.group(1)) <= 4 else None)
    dd = re.search(r'(?<!\d)(\d{1,2})\.?\s+[A-Za-zä]+\s+\d{4}', s) if m and not q else None
    return max(y) + (f'-{m:02d}' + (f'-{int(dd.group(1)):02d}' if dd else '') if m else '')


def econbiz_item(h, B, with_abstract=False):
    """Barrier: date of the work (year only -> year_before_T) AND date of indexing in EconBiz (econbiz_created) < T; DOI -> Crossref recheck."""
    d = econbiz_date(' '.join(h.get('date') or [])); title = h.get('title')
    doi = next((u.split('doi.org/', 1)[1] for u in h.get('identifier_url') or [] if 'doi.org/10.' in u), None)
    if not h.get('id') or not extra_ok(B, [doi, h['id'], 'econbiz:' + h['id']], [year_before_T(d, B) if d and len(d) == 4 else d, h.get('econbiz_created')], [title]): return None
    it = {'id': f'doi:{doi}' if doi else 'econbiz:' + h['id'], 'econbiz': h['id'], 'doi': doi, 'title': title, 'year': d[:4], 'date': d,
          'date_indexed': (h.get('econbiz_created') or '')[:10], 'journal': '; '.join((h.get('isPartOf') or h.get('series') or h.get('publisher') or [])[:1]) or None,
          'first_author': ((h.get('creator') or h.get('person') or [None])[0]), 'type': ', '.join(h.get('type_genre') or [h.get('type') or '']) or None,
          'url': 'https://www.econbiz.de/Record/' + h['id']}
    if with_abstract: it['abstract'] = ' '.join(' '.join(h.get('abstract') or []).split())[:6000] or 'subjects: ' + '; '.join(h.get('subject') or [])[:2000]
    return it


def search_econbiz(q, n, B):
    """EconBiz (ZBW, keyless; Solr): indexing date and year bounded on the provider side (econbiz_created <= eve of T, date_sort <= its year)."""
    lo = B.since or '*'
    qq = f'({q}) AND econbiz_created:[* TO {B.eve}T23:59:59Z] AND date_sort:[{lo} TO {B.eve.year}]'
    r = jget(ECONBIZ + 'search?' + urllib.parse.urlencode({'q': qq, 'size': n}))['hits']
    out = list({x['id']: x for x in (econbiz_item(h, B) for h in r.get('hits', [])) if x}.values())   # one entry per identifier
    return doi_recheck(out, B), r.get('total')


def read_econbiz(ident, B):
    if not re.fullmatch(r'\d{6,14}', ident): return {'refusal': 'expected form econbiz:<record id>, e.g. econbiz:10011386660'}
    try: rec = jget(ECONBIZ + 'record/' + ident).get('record')
    except urllib.error.HTTPError as e:
        if e.code in (400, 404): return {'refusal': 'not found'}
        raise
    it = econbiz_item(rec or {}, B, with_abstract=True)
    return (doi_recheck([it], B) or [{'refusal': 'deposit not attested by Crossref'}])[0] if it else {'refusal': 'not found, after T or forbidden'}


def osv_item(v, B, with_details=False):
    """OSV advisory: refused when `published` is absent or >= T. Modified on/after T: summary, details, ranges and severity are post-T
    edits -> masked (only id, aliases, publication date kept); withdrawn shown only when the withdrawal is before T."""
    vid = v.get('id')
    if not vid or not extra_ok(B, [vid, 'osv:' + vid] + list(v.get('aliases') or []), [v.get('published')], [v.get('summary')]): return None
    fresh = bool(_before(v.get('modified'), B)); keep = (lambda x: x) if fresh else (lambda x: None)
    ranges = [{'package': (a.get('package') or {}).get('name'), 'ecosystem': (a.get('package') or {}).get('ecosystem'),
               'events': [e for r in a.get('ranges') or [] for e in r.get('events') or []][:20]} for a in v.get('affected') or []]
    it = {'id': 'osv:' + vid, 'osv': vid, 'aliases': v.get('aliases') or [], 'date': v.get('published'), 'date_modified': keep(v.get('modified')),
          'withdrawn': _before(v.get('withdrawn'), B), 'summary': keep(v.get('summary')), 'severity': keep(v.get('severity')),
          'affected': keep(ranges), 'references': keep([r.get('url') for r in v.get('references') or []][:8]), 'type': 'advisory',
          'validity': 'advisory unchanged since before T' if fresh else 'advisory modified on/after T: summary, details, ranges and severity masked; the version match uses current ranges'}
    if with_details: it['abstract'] = keep(' '.join(str(v.get('details') or '').split())[:6000]) or '(masked: advisory modified on/after T)'
    return it


def osv_vulns(client, arg, n, B):
    s, p, v = re.fullmatch(sc.OSV_FORM, arg).groups()
    vs = sc.Vulns(client).query(s, p, v)
    out = [x for x in (osv_item(x, B) for x in vs) if x]
    return {'package': p, 'version': v, 'ecosystem': sc.OSV_ECOSYSTEM[s], 'vulns': out[:n]}   # no count of today's advisories (post-T knowledge)


def read_osv(ident, client, B):
    try: v = sc.Vulns(client).get(ident)
    except ValueError as e:
        if str(e) in ('osv_id', 'provider_error:HTTP404'): return {'refusal': 'not found' if 'HTTP404' in str(e) else 'expected form osv:<OSV id>, e.g. osv:GHSA-462w-v97r-4m45'}
        raise
    return osv_item(v, B, with_details=True) or {'refusal': 'after T or forbidden'}


def read_extra(ident, B):
    p, _, v = ident.partition(':'); p = p.lower(); v = v.strip()
    if p == 'osv': return {'refusal': 'osv: identifiers are read through the code engine osv (a plugin must declare it)'}
    return read_nct(v, B) if p == 'nct' else read_dblp(v, B) if p == 'dblp' else read_econbiz(v, B)


ENGINES.update({'clinicaltrials': search_clinicaltrials, 'dblp': search_dblp, 'econbiz': search_econbiz}); CODE_ENGINES['vulns'] = 'osv'   # registry of the extra engines
OSV_FORM_MSG = 'expected form <pypi|npm|cargo|go|maven|rubygems|nuget|packagist>:<package>@<version>'


# ---------------------------------------------------------------- AI engines (plugins/cs-ai.md: openreview, zenodo, hal-info) and code engine `usage` (plugins/code.md)

INTERVAL.update({'api.openreview.net': 2.0, 'api2.openreview.net': 2.0, 'zenodo.org': 2.0})   # OpenReview: limit not published; Zenodo: search 30 req/min (doc)
STOP.update({'api.openreview.net': (403, 429), 'api2.openreview.net': (403, 429), 'zenodo.org': (429,)})   # 403 = ChallengeRequiredError: stop, never worked around


def search_hal_info(q, n, B):
    """HAL, computer science and statistics (level0_domain_s info or stat; no law restriction): same server bounds and barrier as search_hal."""
    rng = f'[{B.start}T00:00:00Z TO {B.eve}T23:59:59Z]'
    r = jget(HAL + '?' + urllib.parse.urlencode([('q', q or '*:*'), ('fq', 'level0_domain_s:(info OR stat)'), ('fq', 'producedDate_tdate:' + rng),
                                                 ('fq', 'submittedDate_tdate:' + rng), ('wt', 'json'), ('fl', HAL_FL), ('rows', n)]))['response']
    return [dict(x, journal='HAL') for x in (hal_item(d, B) for d in r.get('docs', [])) if x], r.get('numFound')


OR_API = ('https://api.openreview.net/', 'https://api2.openreview.net/')   # API v1 (venues before 2023), API v2; /notes/search only
OR_SEEN = 'openreview'                                                      # <state>/openreview/<id>.json: forum notes met by a search (read needs them)
OR_VIS = ('cdate', 'tcdate', 'odate', 'pdate', 'mdate')                     # a forum note is visible when every present date is < T
OR_PENDING = r'(?i)^(submitted to\b|.*\bsubmission$|.*\bunder review\b)'     # venue strings that are not a decision
OR_MIRROR = ('dblp.org', 'openreview.net/archive', 'openreview.net/public_article')   # invitation prefixes (lower case) of mirrored records


def or_day(ms):
    """OpenReview millisecond timestamp -> ISO day (UTC); anything else -> None (refused by the barrier when required)."""
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).date().isoformat() if isinstance(ms, (int, float)) and ms > 0 else None


def or_val(c, k):
    v = (c or {}).get(k)
    return v.get('value') if isinstance(v, dict) else v                       # API v2 wraps every field in {"value": ...}


def or_dates(note, keys): return [or_day(note.get('cdate') or note.get('tcdate'))] + [or_day(note[k]) for k in keys if note.get(k) is not None]


def or_item(note, B, with_abstract=False):
    """Forum note (paper). Visible when cdate, tcdate, odate, pdate and mdate (those present) are < T. tmdate (true modification, also moved
    by platform migrations) gates the content: on/after T the abstract and the venue/decision are masked (a later revision may differ)."""
    c = note.get('content') or {}; title = or_val(c, 'title'); fid = note.get('forum') or note.get('id')
    if not fid or not law_ok(B, [fid, 'openreview:' + str(fid)], or_dates(note, OR_VIS), [title]): return None
    fresh = note.get('tmdate') is None or (or_day(note['tmdate']) is not None and date_upper(or_day(note['tmdate'])) < B.T)
    venue = or_val(c, 'venue') if fresh else None
    inv = note.get('invitation') or (note.get('invitations') or [''])[0]
    mirror = inv.lower().startswith(OR_MIRROR)                                # records mirrored or uploaded outside a reviewed venue: no decision
    decided = bool(venue) and not mirror and not re.match(OR_PENDING, venue)
    it = {'id': 'openreview:' + fid, 'openreview': fid, 'doi': None, 'title': title, 'year': or_day(note.get('cdate') or note.get('tcdate'))[:4],
          'date': or_day(note.get('cdate') or note.get('tcdate')), 'date_public': or_day(note.get('odate')), 'journal': 'OpenReview',
          'venue_id': inv.split('/-/')[0] or None, 'venue': venue, 'decision': venue if decided else None,
          'decision_date': (or_day(note.get('pdate')) or or_day(note.get('mdate')) or or_day(note.get('tmdate'))) if decided else None,
          'first_author': (or_val(c, 'authors') or [None])[0], 'type': 'record' if mirror else 'submission', 'url': 'https://openreview.net/forum?id=' + fid,
          'content': 'unchanged since before T' if fresh else 'modified on/after T (tmdate): abstract, venue and decision masked'}
    if with_abstract: it['abstract'] = ' '.join(str(or_val(c, 'abstract') or '(no abstract available)').split())[:6000] if fresh else '(masked: note modified on/after T)'
    return it


def or_search(api, q, n, source='forum', group='all'):
    return jget(api + 'notes/search?' + urllib.parse.urlencode({'term': q, 'type': 'terms', 'content': 'all', 'group': group, 'source': source, 'limit': n}))


def search_openreview(q, n, B):
    """OpenReview /notes/search (API v1 and v2), forums only. No provider-side date filter exists on this endpoint: local barrier only.
    /notes?id=, ?forum= and /notes/edits answer 403 ChallengeRequiredError (probe 2026-10-28): not used (ACCESS-POLICY.md, level 3)."""
    if not q.strip(): return [], 'empty query'
    per, seen, tot = [], set(), []
    for api in OR_API:
        r = or_search(api, q, n); out = []
        tot.append(str(r.get('count')))
        for note in r.get('notes') or []:
            fid = note.get('forum') or note.get('id')
            if fid in seen or note.get('replyto'): continue
            seen.add(fid)
            try:
                d = STATE / OR_SEEN; d.mkdir(parents=True, exist_ok=True)
                (d / (re.sub(r'[^A-Za-z0-9_-]', '_', fid) + '.json')).write_text(json.dumps(dict(note, _api=api)))
            except OSError: pass
            x = or_item(note, B)
            if x: out.append(x)
        per.append(out)
    out = [x for pair in zip(*per) for x in pair] + [x for o in per for x in o[min(map(len, per)):]]   # v1 and v2 interleaved
    return out[:n], f"provider counts v1 {tot[0]}, v2 {tot[1]} (capped at 10,000; no provider-side date filter: local barrier on cdate, tcdate, odate, pdate, mdate)"


def or_reply(note, B):
    """Review, meta-review, comment or decision: every present date (cdate, tcdate, mdate, tmdate) < T, else never served."""
    if not law_ok(B, [note.get('id')], or_dates(note, ('tcdate', 'mdate', 'tmdate')), []): return None
    c = note.get('content') or {}; inv = note.get('invitation') or (note.get('invitations') or [''])[0]; kind = inv.rsplit('/', 1)[-1]
    text = ' | '.join(f'{k}: {" ".join(str(or_val(c, k)).split())}' for k in c if k not in ('title',) and or_val(c, k) not in (None, ''))
    return {'id': note.get('id'), 'kind': 'decision' if or_val(c, 'decision') or kind == 'Decision' else kind, 'date': or_day(note.get('cdate') or note.get('tcdate')),
            'decision': or_val(c, 'decision'), 'rating': or_val(c, 'rating') or or_val(c, 'recommendation'), 'text': text[:4000]}


def read_openreview(fid, B):
    """Forum note met by an earlier search (the /notes?id= route is behind a challenge), then its public replies found by /notes/search
    (source=reply, title words, venue group), each under the barrier; a decision dated on/after T is never served."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{6,20}', fid): return {'refusal': 'expected form openreview:<forum id>, e.g. openreview:H1ewdiR5tQ'}
    f = STATE / OR_SEEN / (fid + '.json')
    if not f.exists(): return {'refusal': 'unknown forum: run search-openreview first (OpenReview serves a note by id only behind a challenge, not used)'}
    note = json.loads(f.read_text()); api = note.pop('_api', OR_API[1])
    it = or_item(note, B, with_abstract=True)
    if not it: return {'refusal': 'after T or forbidden'}
    reps = [x for x in (or_search(api, it['title'] or fid, 100, 'reply', it['venue_id'] or 'all').get('notes') or []) if x.get('forum') == fid and x.get('id') != fid]
    kept, late, late_dec = [], 0, False
    for r in reps:
        x = or_reply(r, B)
        if x: kept.append(x); continue
        late += 1; late_dec = late_dec or bool(or_val(r.get('content'), 'decision')) or (r.get('invitation') or (r.get('invitations') or [''])[0]).endswith('/Decision')
    dec = next((x for x in kept if x['kind'] == 'decision'), None)
    out = dict(it, reviews=[x for x in kept if x['kind'] != 'decision'], replies_found=len(reps), replies_after_T_or_forbidden=late,
               replies_note='replies found by title search (recall not guaranteed, decision notes often missed); comments CC BY 4.0 (OpenReview terms)')
    if dec: out.update(decision=dec['decision'], decision_date=dec['date'], decision_text=dec['text'])
    elif late_dec: out.update(decision=None, decision_date=None, venue=None, decision_masked='decision dated on/after T: not served (venue masked too)')
    return out


ZENODO = 'https://zenodo.org/api/records'


def zenodo_item(h, B, with_abstract=False):
    """Zenodo record (DataCite DOI: no Crossref recheck): creation AND publication date < T; the record DOI, concept DOI and related
    identifiers checked against the forbidden list; metadata updated on/after T -> description masked (title kept, flagged)."""
    m = h.get('metadata') or {}; title = m.get('title') or h.get('title')
    ids = [h.get('doi') or m.get('doi'), h.get('conceptdoi'), 'zenodo:' + str(h.get('id'))] + [x.get('identifier') for x in m.get('related_identifiers') or []]
    if not h.get('id') or not law_ok(B, ids, [h.get('created'), m.get('publication_date')], [title]): return None
    upd = h.get('updated') or h.get('modified'); fresh = bool(upd) and date_upper(upd) is not None and date_upper(upd) < B.T
    rt = m.get('resource_type') or {}
    it = {'id': f"zenodo:{h['id']}", 'zenodo': h['id'], 'doi': h.get('doi') or m.get('doi'), 'title': title, 'year': str(m.get('publication_date'))[:4],
          'date': m.get('publication_date'), 'date_deposited': str(h.get('created'))[:10], 'journal': 'Zenodo', 'type': rt.get('subtype') or rt.get('type'),
          'first_author': ((m.get('creators') or [{}])[0]).get('name'), 'version': m.get('version'), 'licence': (m.get('license') or {}).get('id'),
          'url': (h.get('links') or {}).get('self_html'), 'metadata': 'unchanged since before T' if fresh else 'updated on/after T: description masked, title as now'}
    if with_abstract: it['abstract'] = ' '.join(html.unescape(re.sub('<[^>]+>', ' ', m.get('description') or '(no description available)')).split())[:6000] if fresh else '(masked: metadata updated on/after T)'
    return it


def search_zenodo(q, n, B):
    """Zenodo REST (keyless): creation and publication dates bounded on the provider side to [start, eve of T], every version listed."""
    qq = f'({q or "*"}) AND created:[{B.start} TO {B.eve}] AND publication_date:[{B.start} TO {B.eve}]'
    r = jget(ZENODO + '?' + urllib.parse.urlencode({'q': qq, 'size': min(n, 25), 'all_versions': 'true', 'sort': 'bestmatch'}))
    return [x for x in (zenodo_item(h, B) for h in (r.get('hits') or {}).get('hits') or []) if x], (r.get('hits') or {}).get('total')


def read_zenodo(rid, B):
    if not rid.isdigit(): return {'refusal': 'expected form zenodo:<record id>, e.g. zenodo:3689089'}
    try: h = jget(f'{ZENODO}/{rid}')
    except urllib.error.HTTPError as e:
        if e.code in (404, 410): return {'refusal': 'not found'}
        raise
    return zenodo_item(h, B, with_abstract=True) or {'refusal': 'after T or forbidden'}


B3_PREFIX = ('openreview:', 'zenodo:')


def read_b3(ident, B):
    p, _, v = ident.partition(':')
    return read_openreview(v.strip(), B) if p.lower() == 'openreview' else read_zenodo(v.strip(), B)


def code_usage(g, arg, n, opt, B, extra):
    """ecosyste.ms package usage. Counts and maintainers are observed NOW (as_of "now"), never as of T; the package must have a release
    published before T; the latest release served is the latest one before T (provider filter published_before, then local check)."""
    m = re.fullmatch(sc.USAGE_FORM, arg)
    if not m: return {'refusal': sc.USAGE_FORM_MSG}
    x = sc.Usage(g.client).lookup(m.group(1), m.group(2), B.T.isoformat())
    rel = [v for v in x.pop('releases_before_T') if B.ok(None, v.get('date'))]          # undated, on/after T: removed and counted
    if not rel: B.excluded += 1; return {'refusal': 'no release published before T (package absent at T or undatable)'}
    first = x.get('first_release_date')
    x.update(latest_release_before_T=rel[0], first_release_date=first if first and B.ok(None, first) else None, date=rel[0]['date'], as_of='now', as_of_note='counts, maintainers, licences: observed now (date of the call), not as of T; only release dates are bounded by T')
    extra['warning'] = 'usage counts are current (as_of "now"), not as of T'
    return x


B3_CODE = {'usage': code_usage}                                           # command -> handler (Gateway._code)
CODE_ENGINES.update({'usage': 'ecosyste.ms'})
ENGINES.update({'openreview': search_openreview, 'zenodo': search_zenodo, 'hal-info': search_hal_info})
# declared source name -> the wired code engine that serves it (tools/check_keys.py: not listed "not wired" when that engine is declared)
SERVED_BY = {'github': 'code', 'sourcegraph': 'code', 'deps.dev': 'versions', 'pypi': 'versions', 'npm': 'versions', 'crates': 'versions',
             'hf-papers': 'paper-code', 'software-heritage': 'provenance'}


# ---------------------------------------------------------------- preprint engines (v0.4.2, plugins/biology.md): biorxiv, medrxiv
# api.biorxiv.org (keyless, no published rate nor terms on the API page; bioRxiv FAQ: "free and unrestricted access ... also to machine analysis")
# has no keyword search (details/pubs by interval or DOI only): the words go to Europe PMC restricted to the server (SRC:PPR AND PUBLISHER:"bioRxiv"),
# bounded on the provider side (FIRST_PDATE and FIRST_IDATE <= eve of T); each hit is then dated on api.biorxiv.org details/<server>/<doi>
# (one row per version: date, title, abstract, published). Metadata and abstract served = latest version posted < T; www.biorxiv.org is never called.

INTERVAL.update({'api.biorxiv.org': 1.0}); STOP.update({'api.biorxiv.org': (403, 429)})   # no published limit: 1 req/s, stop on 403/429
RXIV = 'https://api.biorxiv.org/details/'
RXIV_SERVER = {'biorxiv': 'bioRxiv', 'medrxiv': 'medRxiv'}
RXIV_DOI = r'10\.(?:1101|64898)/(?:\d{4}\.\d{2}\.\d{2}\.)?\d{6,8}'   # openRxiv preprint DOIs (10.64898 for new posts, measured 2026-10-28); 10.1101/gad.x = CSHL journals


def rxiv_versions(server, doi):
    """Every version (sorted) of a preprint on api.biorxiv.org; [] when the server has no such post; ProviderError on any other answer."""
    r = jget(RXIV + server + '/' + doi + '/na/json')
    st = str(((r.get('messages') or [{}])[0] or {}).get('status') or '')
    if st != 'ok':
        if 'no posts' in st.lower(): return []
        raise ProviderError(f'provider_error: api.biorxiv.org answered "{st[:60]}" (not an empty result)')
    return sorted(r.get('collection') or [], key=lambda v: int(v['version']) if str(v.get('version', '')).isdigit() else 0)


def rxiv_item(server, doi, rows, B, epmc=None, with_abstract=False):
    """Barrier: preprint DOI, published-article DOI (any date) and every title (all versions, Europe PMC) against the forbidden lists; first
    version posted < T (and Europe PMC first publication and indexing < T when the hit comes from a search); no date -> refused.
    Served: the latest version posted < T; later versions are never read (later_versions_masked); published_doi set by rxiv_published."""
    pub = next((v.get('published') for v in reversed(rows) if v.get('published') not in (None, '', 'NA')), None)
    first = rows[0] if rows else {}
    dates = [first.get('date')] + ([epmc.get('firstPublicationDate'), epmc.get('firstIndexDate')] if epmc is not None else [])
    if not rows or not extra_ok(B, [doi, server + ':' + doi, pub], dates, [v.get('title') for v in rows] + [(epmc or {}).get('title')]): return None
    seen = [v for v in rows if _before(v.get('date'), B)]
    if not seen: B.excluded += 1; return None
    cur = seen[-1]; ver = str(cur.get('version') or '')
    it = {'id': 'doi:' + doi, 'doi': doi, 'server': RXIV_SERVER[server], 'title': cur.get('title'), 'year': first['date'][:4], 'date': first['date'][:10],
          'date_version': (cur.get('date') or '')[:10], 'version': ver, 'journal': RXIV_SERVER[server], 'first_author': (cur.get('authors') or '').split(';')[0].strip() or None,
          'category': cur.get('category'), 'license': cur.get('license'), 'type': 'preprint', 'peer_review': 'not peer reviewed (preprint)',
          'later_versions_masked': len(seen) < len(rows), 'published_doi': None, '_pub': pub,
          'url': f'https://www.{server}.org/content/{doi}v{ver}'}
    if with_abstract: it['abstract'] = ' '.join(str(cur.get('abstract') or '(no abstract available)').split())[:6000]
    return it


def rxiv_published(items, B):
    """The published-article link is shown only when Crossref attests its deposit AND publication < T (crossref_batch, strict); otherwise
    nothing is said about it (a publication on/after T is post-T knowledge). Not counted as an exclusion: the preprint itself stays."""
    pubs = [x['_pub'] for x in items if x.get('_pub')]; k = B.excluded
    try: ok = {c['id'][4:].lower(): c for c in crossref_batch(pubs, B)} if pubs else {}
    except Exception: ok = {}                                            # Crossref unreachable: link not attested -> not shown
    B.excluded = k
    for x in items:
        c = ok.get((x.pop('_pub', None) or '').lower())
        if c: x.update(published_doi=c['id'][4:], published_journal=c.get('journal'), published_year=c.get('year'))
    return items


def search_rxiv(server, q, n, B):
    qq = f'({q}) AND SRC:PPR AND PUBLISHER:"{RXIV_SERVER[server]}" AND FIRST_PDATE:[{B.start} TO {B.eve}] AND FIRST_IDATE:[{B.start} TO {B.eve}]'
    r = jget(EPMC + 'search?format=json&resultType=lite&pageSize=' + str(n) + '&query=' + urllib.parse.quote(qq))
    out, seen, undated, down = [], set(), 0, None
    for h in r.get('resultList', {}).get('result', []):
        doi = re.sub(r'v\d+$', '', (h.get('doi') or '').strip().lower())
        if doi in seen: continue
        seen.add(doi)
        if not re.fullmatch(RXIV_DOI, doi): B.excluded += 1; continue  # no openRxiv DOI: cannot be dated on the server -> refused
        if down: undated += 1; continue
        try: rows = rxiv_versions(server, doi)
        except Exception as e: down = str(e)[:80]; undated += 1; continue   # first failure stops the host for this call (no retry storm)
        x = rxiv_item(server, doi, rows, B, epmc=h)
        if x: out.append(x)
        elif not rows: B.excluded += 1
    if down and not out: raise ProviderError(f'provider_error: api.biorxiv.org unavailable ({down}); {undated} hits not datable (not an empty result)')
    return rxiv_published(out, B), (r.get('hitCount') if not undated else f"{r.get('hitCount')} in Europe PMC; {undated} hits not datable (api.biorxiv.org: {down})")


def search_biorxiv(q, n, B):
    """bioRxiv preprints: Europe PMC words (SRC:PPR, PUBLISHER bioRxiv, v1 posted and indexed <= eve of T), each hit dated on api.biorxiv.org."""
    return search_rxiv('biorxiv', q, n, B)


def search_medrxiv(q, n, B):
    """medRxiv preprints: same route as search_biorxiv (PUBLISHER medRxiv)."""
    return search_rxiv('medrxiv', q, n, B)


def rxiv_ident(ident):
    """'biorxiv:<doi>' | 'medrxiv:<doi>' -> (server, doi); 'doi:<openRxiv preprint DOI>' or the bare DOI -> (None, doi); else None."""
    p, _, v = ident.strip().partition(':'); p = p.lower()
    if p in RXIV_SERVER: return p, v.strip()
    d = re.sub(r'v\d+$', '', (v if p == 'doi' else ident).strip().replace('https://doi.org/', '').lower())
    return (None, d) if re.fullmatch(RXIV_DOI, d) else None


def rxiv_lookup(server, doi):
    """-> (server, rows); an unnamed server: medRxiv first for an 8-digit suffix, else bioRxiv, then the other one."""
    for s in [server] if server else (['medrxiv', 'biorxiv'] if len(doi.rsplit('.', 1)[-1]) == 8 else ['biorxiv', 'medrxiv']):
        rows = rxiv_versions(s, doi)
        if rows: return s, rows
    return server, []


def read_rxiv(server, doi, B, published=True):
    """Notice and abstract of the latest version posted before T (v1 < T required)."""
    doi = re.sub(r'v\d+$', '', doi.strip().replace('https://doi.org/', '').lower())
    if not re.fullmatch(RXIV_DOI, doi): return {'refusal': 'expected form biorxiv:<DOI> | medrxiv:<DOI>, e.g. biorxiv:10.1101/2020.03.22.002386'}
    s, rows = rxiv_lookup(server, doi)
    if not rows: return {'refusal': 'not found on api.biorxiv.org'}
    it = rxiv_item(s, doi, rows, B, with_abstract=True)
    if not it: return {'refusal': 'after T or forbidden'}
    return rxiv_published([it], B)[0] if published else it


_read_core, _citing_core, _references_core = read, citing, references    # preprint DOIs are routed here: the core DOI read (Europe PMC core) serves the latest version


def read(ident, B):
    r = rxiv_ident(ident)
    return read_rxiv(r[0], r[1], B) if r else _read_core(ident, B)


def citing(ident, n, B):
    r = rxiv_ident(ident)
    if r and 'refusal' in read_rxiv(r[0], r[1], B, published=False): return [], 'document after T, forbidden or not found'
    return _citing_core('doi:' + r[1] if r else ident, n, B)


def references(ident, n, B):
    r = rxiv_ident(ident)
    if r and 'refusal' in read_rxiv(r[0], r[1], B, published=False): return [], 'document after T, forbidden or not found'
    return _references_core('doi:' + r[1] if r else ident, n, B)


ENGINES.update({'biorxiv': search_biorxiv, 'medrxiv': search_medrxiv})   # registry of the preprint engines


# ---------------------------------------------------------------- CS engines (v0.4.6, plugins/cs-ai.md): hf-models, hf-datasets, standards, proceedings; command related
# All keyless (probes 2026-10-28). Index files (RFC index, PEP index, W3C list, ACL bib, PMLR volume feeds, CVF listings) are fetched once,
# kept in the fetch cache, parsed once into <state>/cs-index/<name>.json; the title search is local. Hosts stop at once on 403/404/429.

CS = CFG.get('cs_engines') or {}
CS_HOSTS = ('huggingface.co', 'www.rfc-editor.org', 'peps.python.org', 'api.w3.org', 'www.w3.org', 'api.github.com', 'raw.githubusercontent.com',
            'aclanthology.org', 'proceedings.mlr.press', 'openaccess.thecvf.com')
INTERVAL.update({h: 2.0 for h in CS_HOSTS}); INTERVAL.update({'huggingface.co': 1.0, 'api.w3.org': 1.0})   # HF 500 req/5 min, W3C 6,000/10 min (doc)
STOP.update({h: (401, 403, 404, 410, 429) for h in CS_HOSTS})
CS_PREFIX = ('hfmodel:', 'hfdataset:', 'rfc:', 'pep:', 'w3c:', 'acl:', 'pmlr:', 'cvf:')


def cs_index(name, build):
    """Parsed index <state>/cs-index/<name>.json (built once from cached index files; not T-dependent: the barrier is applied per item)."""
    f = STATE / 'cs-index' / (re.sub(r'[^\w.-]', '_', name) + '.json')
    if f.exists(): return json.loads(f.read_text())
    x = build()
    if x: f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(x))   # an empty parse is never kept
    return x


def cs_match(q, recs, text):
    """Local title search: every query word (3 letters or more) present in text(rec); -> [(words in the title, rec)]."""
    qt = tokens(q)
    if not qt: return []
    out = []
    for r in recs:
        tt = tokens(r.get('title') or '')
        if qt <= tt or qt <= tt | tokens(text(r)): out.append((len(qt & tt), r))
    return out


def cs_text(s, k=6000): return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', s or '')).split())[:k]


def http_code(e): return getattr(e, 'code', None)


# ---- Hugging Face Hub (models, datasets). Terms: no clause against automated use; robots "Allow: /"; anonymous 500 req / 5 min / IP.
HF = 'https://huggingface.co/'
HF_KIND = {'hfmodel': 'models', 'hfdataset': 'datasets'}
HF_LEGACY = '2022-03-02'   # Hub migration day: every older repo carries this createdAt (probe 2026-10-28) -> existence attested by a commit dated < T
HF_REPO = r'[A-Za-z0-9][\w.-]{0,95}(/[A-Za-z0-9][\w.-]{0,95})?'


def hf_licence(card, tags):
    l = (card or {}).get('license')
    return l if isinstance(l, str) else next((t[8:] for t in tags or [] if str(t).startswith('license:')), None)


def hf_commit(kind, rid, B):
    """Last commit of main dated < T (newest-first pages of 100, at most cs_engines.hf_commit_pages) -> (commit, newer commits seen) or (None, n)."""
    newer = 0
    for p in range(int(CS.get('hf_commit_pages', 10))):
        page = jget(f'{HF}api/{kind}/{rid}/commits/main?limit=100&p={p}')
        for c in page or []:
            if _before(c.get('date'), B): return c, newer
            newer += 1
        if len(page or []) < 100: break
    return None, newer


def hf_item(r, kind, B, legacy_check=None):
    """Hub repo: created < T (createdAt; a repo of the migration day is attested by a commit dated < T); its id, linked arXiv papers
    (tags arxiv:) checked against the forbidden lists. Downloads and likes are current (as_of "now"); licence, task and tags only when
    lastModified < T (nothing changed since), else masked (read the card at the revision before T). legacy_check: [remaining commit lookups]."""
    rid = r.get('id') or r.get('modelId'); tags = r.get('tags') or []; created = r.get('createdAt'); pre = 'hfmodel' if kind == 'models' else 'hfdataset'
    ids = [rid, f'{pre}:{rid}'] + ['10.48550/arxiv.' + t[6:] for t in tags if str(t).startswith('arxiv:')]
    dates = [created]
    if created and str(created)[:10] == HF_LEGACY and not _before(created, B):
        if not legacy_check or legacy_check[0] <= 0: dates = [None]              # lookup budget spent: not datable -> refused
        else: legacy_check[0] -= 1; c, _ = hf_commit(kind, rid, B); dates = [c.get('date') if c else None]
    if not rid or not law_ok(B, ids, dates, [rid]): return None
    fresh = _before(r.get('lastModified'), B) is not None
    it = {'id': f'{pre}:{rid}', pre: rid, 'title': rid, 'date': str(dates[0])[:10], 'date_created': str(created)[:10] if _before(created, B) else None, 'journal': 'Hugging Face Hub',
          'type': 'model' if kind == 'models' else 'dataset', 'first_author': r.get('author') or rid.split('/')[0],
          'downloads': r.get('downloads'), 'likes': r.get('likes'), 'as_of': 'now', 'url': HF + ('datasets/' if kind == 'datasets' else '') + rid,
          'metadata': 'unchanged since before T (lastModified < T)' if fresh else 'modified on/after T: licence, task and tags masked (read the card at the revision before T)'}
    if fresh:
        it.update(licence=hf_licence(r.get('cardData'), tags), task=r.get('pipeline_tag') or [t[16:] for t in tags if str(t).startswith('task_categories:')] or None,
                  library=r.get('library_name'), arxiv=[t[6:] for t in tags if str(t).startswith('arxiv:')])
    if dates[0] != created: it['date_note'] = 'repository older than the Hub migration (createdAt 2022-03-02): existence dated by its last commit before T'
    return it


def search_hf(kind, q, n, B):
    """Hub search (`search=` on the repo id, most downloaded first; no provider-side date filter): local barrier on createdAt."""
    if not q.strip(): return [], 'empty query'
    rs = jget(f'{HF}api/{kind}?' + urllib.parse.urlencode({'search': q.strip(), 'limit': min(100, 3 * n), 'full': 'true', 'sort': 'downloads', 'direction': -1}))
    out, budget = [], [n]                                                    # at most n commit lookups for repos of the migration day
    for r in rs or []:
        if len(out) >= n: break
        x = hf_item(r, kind, B, budget)
        if x: out.append(x)
    return out, (f'{len(rs or [])} repos returned (search on the repo id, no provider-side date filter: local barrier on createdAt; repos of the 2022-03-02 '
                 f'migration day dated by a commit, {n - budget[0]} lookups); downloads and likes as_of now')


def search_hf_models(q, n, B): return search_hf('models', q, n, B)


def search_hf_datasets(q, n, B): return search_hf('datasets', q, n, B)


def hf_evals(mi):
    """model-index (declared in the card at the revision) -> flat list of self-reported results."""
    out = []
    for m in mi if isinstance(mi, list) else []:
        for r in (m or {}).get('results') or [] if isinstance(m, dict) else []:
            if not isinstance(r, dict): continue
            t, d = r.get('task') or {}, r.get('dataset') or {}
            for x in r.get('metrics') or []:
                if isinstance(x, dict): out.append({'task': t.get('type') or t.get('name'), 'dataset': d.get('name') or d.get('type'), 'config': d.get('config'),
                                                    'split': d.get('split'), 'metric': x.get('name') or x.get('type'), 'value': x.get('value'), 'verified': bool(x.get('verified'))})
    return out[:60]


def read_hf(pre, rid, B):
    """Repo created < T; the card (metadata, model-index, README text) is read at the last commit of main dated < T, never today's."""
    if not re.fullmatch(HF_REPO, rid) or '..' in rid: return {'refusal': f'expected form {pre}:<owner>/<name>, e.g. hfmodel:google-bert/bert-base-uncased'}
    kind = HF_KIND[pre]
    try: info = jget(f'{HF}api/{kind}/{rid}')
    except urllib.error.HTTPError as e:
        if http_code(e) in (401, 403, 404, 410): return {'refusal': f'not found, private or gated (HTTP {http_code(e)})'}
        raise
    c, newer = hf_commit(kind, rid, B)
    if not c: B.excluded += 1; return {'refusal': 'no commit dated before T (repository absent or empty at T)'}
    leg = str(info.get('createdAt'))[:10] == HF_LEGACY and not _before(info.get('createdAt'), B)   # migration day on/after T: the commit < T attests existence
    it = hf_item(dict(info, lastModified=None, createdAt=c.get('date') if leg else info.get('createdAt')), kind, B)
    if not it: return {'refusal': 'after T or forbidden'}
    if leg: it.update(date_created=None, date_note='repository older than the Hub migration (createdAt 2022-03-02): existence dated by its last commit before T')
    sha = c['id']
    try: rev = jget(f'{HF}api/{kind}/{rid}/revision/{sha}')
    except urllib.error.HTTPError as e:
        if http_code(e) not in (401, 403, 404): raise
        rev = {}                                                              # gated: metadata at the revision not readable, nothing else served
    card = rev.get('cardData') if isinstance(rev.get('cardData'), dict) else {}
    try:
        txt = fetch(f"{HF}{'datasets/' if kind == 'datasets' else ''}{rid}/raw/{sha}/README.md").decode('utf-8', 'replace')
        txt = re.sub(r'(?s)\A---\n.*?\n---\n', '', txt).strip()[:6000] or '(empty card)'
    except Exception as e: txt = f'(card text not available at this revision: {str(e)[:60]})'
    it.update(metadata='read at the revision before T', revision=sha, revision_date=str(c.get('date'))[:10], later_commits_masked=newer,
              licence=hf_licence(card, rev.get('tags')), task=card.get('pipeline_tag') or rev.get('pipeline_tag') or card.get('task_categories'),
              library=card.get('library_name') or rev.get('library_name'), datasets=card.get('datasets'), language=card.get('language'),
              eval_results=hf_evals(card.get('model-index') or rev.get('model-index')), eval_note='self-reported in the model card (model-index); verified=true only when the Hub marks it',
              abstract=txt, as_of_note='downloads and likes: observed now (date of the call), not as of T; everything else at the revision before T')
    return it


# ---- Standards: IETF RFCs (rfc-editor.org index and text), Python PEPs (peps.python.org index; text from python/peps at a commit), W3C (api.w3.org)
RFC_INDEX = 'https://www.rfc-editor.org/rfc-index.xml'
PEP_INDEX = 'https://peps.python.org/api/peps.json'
W3C = 'https://api.w3.org/specifications'


def rfc_index():
    def build():
        root = ET.fromstring(fetch(RFC_INDEX)); out = {}
        for e in root.findall('{*}rfc-entry'):
            g = lambda t: (e.findtext('{*}' + t) or '').strip()
            ids = lambda t: [x.text.strip() for x in e.findall('{*}' + t + '/{*}doc-id') if x.text]
            d = e.find('{*}date'); dd = lambda t: ((d.findtext('{*}' + t) if d is not None else '') or '').strip()
            out[g('doc-id')] = {'n': g('doc-id')[3:].lstrip('0'), 'title': g('title'), 'date': ' '.join(x for x in (dd('year'), dd('month'), dd('day')) if x),
                                'abstract': ' '.join(' '.join(p.itertext()) for p in e.findall('{*}abstract/{*}p')), 'kw': [k.text for k in e.findall('{*}keywords/{*}kw') if k.text],
                                'author': (e.findtext('{*}author/{*}name') or '').strip(), 'status': g('publication-status'), 'stream': g('stream'), 'doi': g('doi'),
                                'obsoletes': ids('obsoletes'), 'obsoleted_by': ids('obsoleted-by'), 'updates': ids('updates'), 'updated_by': ids('updated-by')}
        return out
    return cs_index('rfc-index', build)


def rfc_item(rec, idx, B):
    """RFC: publication month < T (upper bound of the month, strict). Obsoleted-by / updated-by only through RFCs published < T; the current
    status (undated reclassification) is never served, the status at publication is. RFC DOIs were deposited retroactively: no Crossref recheck."""
    n = rec['n']
    if not law_ok(B, [rec.get('doi'), f'rfc:{n}', f'RFC{n}'], [rec.get('date')], [rec.get('title')]): return None
    seen = lambda xs: [x for x in xs if x in idx and _before(idx[x]['date'], B)]
    return {'id': f'rfc:{n}', 'rfc': n, 'doi': rec.get('doi') or None, 'title': rec['title'], 'year': rec['date'][:4], 'date': rec['date'], 'journal': 'IETF RFC',
            'type': 'standard', 'first_author': rec.get('author'), 'status_at_publication': rec.get('status'), 'stream': rec.get('stream'),
            'obsoletes': rec.get('obsoletes'), 'updates': rec.get('updates'), 'obsoleted_by': seen(rec.get('obsoleted_by') or []), 'updated_by': seen(rec.get('updated_by') or []),
            'status_note': 'current status not served (undated); obsoleted_by and updated_by list only RFCs published before T', 'url': f'https://www.rfc-editor.org/rfc/rfc{n}'}


def pep_date(s):
    for f in ('%d-%b-%Y', '%Y-%m-%d', '%d %B %Y', '%d-%B-%Y'):
        try: return dt.datetime.strptime(str(s).strip(), f).date().isoformat()
        except ValueError: pass
    return None


def pep_index(): return cs_index('pep-index', lambda: jget(PEP_INDEX))


def pep_item(rec, idx, B):
    """PEP: created < T. Status, Python version and resolution are not served from the index (they change without a date): read pep:<n>
    gives them from the header of the text at the last commit before T. superseded_by only when the superseding PEP was created < T."""
    n = str(rec.get('number')); d = pep_date(rec.get('created'))
    if not law_ok(B, [f'pep:{n}'], [d], [rec.get('title')]): return None
    sup = [x.strip() for x in str(rec.get('superseded_by') or '').split(',') if x.strip()]
    return {'id': f'pep:{n}', 'pep': n, 'title': rec.get('title'), 'year': d[:4], 'date': d, 'journal': 'Python PEP', 'type': 'standard',
            'first_author': (rec.get('author_names') or [None])[0], 'pep_type': rec.get('type'), 'topic': rec.get('topic') or None,
            'superseded_by': [x for x in sup if x in idx and _before(pep_date(idx[x].get('created')), B)], 'replaces': rec.get('replaces'),
            'status': None, 'status_note': f'status not served from the index (undated changes): read pep:{n} (header at the last commit before T)', 'url': rec.get('url')}


def w3c_index():
    def build():
        out = []
        for p in (1, 2, 3):
            r = jget(f'{W3C}?items=1000&page={p}')
            out += [{'sn': x['href'].rstrip('/').rsplit('/', 1)[-1], 'title': x.get('title') or ''} for x in (r.get('_links') or {}).get('specifications') or []]
            if p >= int(r.get('pages') or 1): break
        return out
    return cs_index('w3c-index', build)


def w3c_item(sn, title, B):
    """W3C specification: first published version < T; served = the latest version dated < T (its status, title, dated URI); later masked."""
    if not re.fullmatch(r'[\w.-]{1,80}', sn): return None
    try: r = jget(f'{W3C}/{sn}/versions?embed=true&items=1000')
    except urllib.error.HTTPError as e:
        if http_code(e) in (404, 410): return None
        raise
    vs = sorted((v for v in (r.get('_embedded') or {}).get('version-history') or [] if v.get('date')), key=lambda v: v['date'])
    if not vs: B.excluded += 1; return None
    if not law_ok(B, [f'w3c:{sn}'], [vs[0]['date']], [title or vs[-1].get('title')]): return None
    seen = [v for v in vs if _before(v['date'], B)]
    if not seen: B.excluded += 1; return None
    cur = seen[-1]
    return {'id': f'w3c:{sn}', 'w3c': sn, 'title': cur.get('title') or title, 'year': vs[0]['date'][:4], 'date': vs[0]['date'], 'date_version': cur['date'],
            'journal': 'W3C', 'type': 'standard', 'status': cur.get('status'), 'status_note': 'status of the latest version dated before T',
            'later_versions_masked': len(vs) - len(seen), 'url': cur.get('uri')}


def search_standards(q, n, B):
    """RFC index (title, keywords, abstract), PEP index (title), W3C list (title): every query word present; most title words first, then
    most recent; W3C hits are dated one call each (at most cs_engines.w3c_lookups per search)."""
    if not tokens(q): return [], 'no usable word (3 letters or more)'
    ri, pi = rfc_index(), pep_index()
    hits = [(s, 'rfc', r) for s, r in cs_match(q, ri.values(), lambda r: ' '.join([r.get('abstract') or ''] + (r.get('kw') or [])))]
    hits += [(s, 'pep', r) for s, r in cs_match(q, pi.values(), lambda r: r.get('topic') or '')]
    w3 = [(s, 'w3c', r) for s, r in cs_match(q, w3c_index(), lambda r: r['sn'].replace('-', ' '))]
    key = lambda h: (h[0], str(date_upper(h[2].get('date') or pep_date(h[2].get('created')) or '') or ''))
    hits = sorted(hits, key=key, reverse=True); w3 = sorted(w3, key=lambda h: h[0], reverse=True)[:int(CS.get('w3c_lookups', 8))]
    out, ordered = [], [h for pair in zip(hits, w3) for h in pair] + hits[len(w3):] + w3[len(hits):]   # W3C hits interleaved (no date before lookup)
    for s, k, r in ordered:
        if len(out) >= n: break
        x = rfc_item(r, ri, B) if k == 'rfc' else pep_item(r, pi, B) if k == 'pep' else w3c_item(r['sn'], r['title'], B)
        if x: out.append(x)
    nr = sum(1 for h in hits if h[1] == 'rfc')
    return out, f'local indexes, all dates: RFC {nr}, PEP {len(hits) - nr}, W3C {len(w3)} looked up (rfc-index.xml, peps.json, api.w3.org list)'


def read_standard(p, v, B):
    v = v.strip()
    if p == 'rfc':
        n = v.upper().removeprefix('RFC').lstrip('0')
        if not n.isdigit(): return {'refusal': 'expected form rfc:<number>, e.g. rfc:8446'}
        ri = rfc_index(); rec = ri.get('RFC' + n.zfill(4)) or ri.get('RFC' + n)
        if not rec: return {'refusal': 'not found in the RFC index'}
        it = rfc_item(rec, ri, B)
        if not it: return {'refusal': 'after T or forbidden'}
        try: txt = fetch(f'https://www.rfc-editor.org/rfc/rfc{n}.txt').decode('utf-8', 'replace')
        except Exception as e: txt = f'(text not available: {str(e)[:60]})'
        return dict(it, abstract=' '.join((rec.get('abstract') or '(no abstract in the index)').split())[:6000], text=txt[:TEXT_HEAD],
                    text_note=f'RFC text, immutable once published; first {TEXT_HEAD} characters')
    if p == 'pep':
        if not v.isdigit(): return {'refusal': 'expected form pep:<number>, e.g. pep:484'}
        pi = pep_index(); rec = pi.get(str(int(v)))
        if not rec: return {'refusal': 'not found in the PEP index'}
        it = pep_item(rec, pi, B)
        if not it: return {'refusal': 'after T or forbidden'}
        k = int(v)
        for path in (f'peps/pep-{k:04d}.rst', f'pep-{k:04d}.rst', f'pep-{k:04d}.txt'):   # files moved to peps/ in 2023; .txt before .rst
            cs = jget('https://api.github.com/repos/python/peps/commits?' + urllib.parse.urlencode({'path': path, 'until': f'{B.eve}T23:59:59Z', 'per_page': 1}))
            c = (cs or [None])[0]
            if not c: continue
            cd = [((c.get('commit') or {}).get(w) or {}).get('date') for w in ('author', 'committer')]
            if not all(_before(x, B) for x in cd): continue
            txt = fetch(f"https://raw.githubusercontent.com/python/peps/{c['sha']}/{path}").decode('utf-8', 'replace')
            head = dict(re.findall(r'(?m)^([A-Z][\w-]+):\s*(.*)$', txt.split('\n\n', 1)[0]))
            return dict(it, status=head.get('Status'), status_note='from the header of the text at the last commit before T', python_version=head.get('Python-Version'),
                        superseded_by_at_T=head.get('Superseded-By'), resolution=head.get('Resolution'), revision=c['sha'], revision_date=str(cd[1])[:10],
                        abstract=txt[:TEXT_HEAD], text_note=f'python/peps {path} at {c["sha"][:12]} (last commit before T); first {TEXT_HEAD} characters')
        B.excluded += 1
        return {'refusal': 'no version of the PEP text dated before T found in python/peps (GitHub)'}
    it = w3c_item(v, None, B)
    if not it: return {'refusal': 'not found, after T or forbidden'}
    try:
        page = fetch(it['url']).decode('utf-8', 'replace')
        m = re.search(r'(?is)<(section|div)[^>]*\bid=["\']?abstract["\']?[^>]*>(.*?)</\1>', page) or re.search(r'(?is)<h2[^>]*>(?:<[^>]+>)*\s*Abstract\s*(?:<[^>]+>)*</h2>(.*?)<h2', page)
        ab = cs_text(m.group(m.lastindex)) if m else '(no abstract found in the dated version)'
    except Exception as e: ab = f'(dated version not available: {str(e)[:60]})'
    return dict(it, abstract=ab, text_note='abstract of the dated version (www.w3.org/TR/<year>/...), immutable')


# ---- Open-access proceedings: ACL Anthology (anthology.bib.gz, CC BY 4.0), PMLR (volume RSS feeds), CVF open access (conference listings)
ACL = 'https://aclanthology.org/'
PMLR = 'https://proceedings.mlr.press/'
CVF = 'https://openaccess.thecvf.com/'
MO3 = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
BIB_FIELD = re.compile(r'(\w+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}|(\w+(?:\s*#\s*(?:"[^"]*"|\w+))*))', re.S)   # bare value: `jun # "--" # jul` kept whole


def bib_entries(txt):
    """BibTeX -> [dict] (inproceedings and article only); braces dropped from values."""
    out = []
    for chunk in re.split(r'\n(?=@)', '\n' + txt):
        m = re.match(r'\s*@(\w+)\s*\{\s*([^,\s]+)\s*,', chunk)
        if not m or m.group(1).lower() not in ('inproceedings', 'article'): continue
        f = {k.lower(): ' '.join(re.sub(r'[{}]', '', a or b or c).split()) for k, a, b, c in BIB_FIELD.findall(chunk[m.end():])}
        out.append(f)
    return out


def acl_rec(f):
    mons = [w for w in re.findall(r'[a-z]+', (f.get('month') or '').lower()) if w[:3] in MO3]
    return {'id': (f.get('url') or '').rstrip('/').rsplit('/', 1)[-1], 'title': f.get('title'), 'year': f.get('year'), 'month': mons[-1][:3] if mons else None,
            'venue': f.get('booktitle') or f.get('journal'), 'doi': f.get('doi') or None, 'author': (f.get('author') or '').split(' and ')[0].split(',')[0].strip() or None}


def acl_index():
    import gzip
    return cs_index('acl-anthology', lambda: [r for r in (acl_rec(f) for f in bib_entries(gzip.decompress(fetch(ACL + 'anthology.bib.gz')).decode('utf-8', 'replace'))) if r['id']])


def acl_item(r, B):
    """ACL paper: month of the volume < T (upper bound of the month; the LAST month of a range), year only -> strictly before the year of T;
    a DOI is rechecked on Crossref afterwards (doi_recheck)."""
    d = f"{r['year']} {r['month'].capitalize()}" if r.get('month') and r.get('year') else year_before_T(r.get('year'), B)
    if not law_ok(B, [r.get('doi'), 'acl:' + r['id']], [d], [r.get('title')]): return None
    return {'id': 'acl:' + r['id'], 'acl': r['id'], 'doi': r.get('doi'), 'title': r.get('title'), 'year': r.get('year'), 'date': d if r.get('month') else r.get('year'),
            'journal': r.get('venue'), 'venue': 'ACL Anthology', 'type': 'proceedings', 'first_author': r.get('author'), 'url': ACL + r['id'] + '/'}


PMLR_VENUES = ('ICML', 'AISTATS', 'COLT', 'UAI', 'CoRL', 'ALT', 'ACML', 'L4DC', 'CLeaR', 'MIDL', 'CHIL', 'LoG')   # main conferences, in order of priority
PMLR_MAIN = r'(?:Proceedings of (?:the )?)?(' + '|'.join(PMLR_VENUES) + r') (\d{4})(?: Proceedings)?'


def pmlr_volumes():
    """PMLR main-conference volumes listed on the home page -> [(volume, venue, year)] by volume number, newest first."""
    def build():
        t = fetch(PMLR).decode('utf-8', 'replace'); out = []
        for v, label in re.findall(r'<a href="/?(v\d+)/?"><b>Volume \d+</b></a>\s*([^<]+)', t):
            m = re.fullmatch(PMLR_MAIN, label.strip())
            if m: out.append([v, m.group(1), int(m.group(2))])
        return sorted(out, key=lambda x: -int(x[0][1:]))
    return cs_index('pmlr-volumes', build)


def pmlr_volume(v):
    """Volume RSS feed -> {'date': publication of the volume, 'label', 'papers': [{id, title, abstract}]}."""
    def build():
        root = ET.fromstring(fetch(f'{PMLR}{v}/assets/rss/feed.xml')); ch = root.find('channel')
        desc = ch.findtext('description') or ''
        m = re.search(r'Published as Volume \d+ by the Proceedings of Machine Learning Research on (\d{1,2} \w+ \d{4})', desc)
        d = None
        if m:
            try: d = dt.datetime.strptime(m.group(1), '%d %B %Y').date().isoformat()
            except ValueError: d = None
        ps = []
        for it in ch.findall('item'):
            link = it.findtext('link') or ''; k = re.search(r'/(v\d+/[\w.-]+?)\.html', link)
            if k: ps.append({'id': k.group(1), 'title': ' '.join((it.findtext('title') or '').split()), 'abstract': cs_text(it.findtext('description'), 2000)})
        return {'date': d, 'label': ' '.join(desc.split('\n', 1)[0].split()), 'papers': ps}
    return cs_index('pmlr-' + v, build)


def pmlr_item(r, vol, year, B):
    d = vol.get('date') or year_before_T(year, B)
    if not law_ok(B, ['pmlr:' + r['id']], [d], [r.get('title')]): return None
    return {'id': 'pmlr:' + r['id'], 'pmlr': r['id'], 'doi': None, 'title': r.get('title'), 'year': str(year), 'date': vol.get('date') or str(year),
            'journal': vol.get('label'), 'venue': 'PMLR', 'type': 'proceedings', 'url': f"{PMLR}{r['id']}.html"}


def cvf_confs():
    """CVF main conferences (menu) -> [(conference, year, published date or None)], newest first."""
    def build():
        t = fetch(CVF + 'menu').decode('utf-8', 'replace'); out = []
        for c, d in re.findall(r'\[<a href="/?((?:CVPR|ICCV|WACV)\d{4})(?:\.py)?">Main Conference</a>\]\s*(?:<span[^>]*>\(Published: ([^)]+)\))?', t):
            try: d = dt.datetime.strptime(d.strip(), '%B %d, %Y').date().isoformat() if d else None
            except ValueError: d = None
            out.append([c, int(c[-4:]), d])
        return sorted(out, key=lambda x: (x[1], x[2] or ''), reverse=True)
    return cs_index('cvf-confs', build)


def cvf_papers(conf):
    def build():
        t = fetch(f'{CVF}{conf}?day=all').decode('utf-8', 'replace'); pages = [t]
        if 'paper.html' not in t:                                         # older conferences: one listing per day, linked from the bare page
            t = fetch(CVF + conf).decode('utf-8', 'replace')
            pages = [fetch(f'{CVF}{conf}?day={d}').decode('utf-8', 'replace') for d in sorted(set(re.findall(r'href="/?' + conf + r'(?:\.py)?\?day=([\w-]+)"', t))) if d != 'all']
        ps = {}
        for p in pages:
            for path, title in re.findall(r'<dt class="ptitle">\s*(?:<br>)?\s*<a href="/?([\w./-]+?_paper)\.html">(.*?)</a>', p, re.S): ps[path] = cs_text(title, 400)
        return [{'id': k, 'title': v} for k, v in ps.items()]
    return cs_index('cvf-' + conf, build)


def cvf_item(r, conf, year, d, B):
    dd = d or year_before_T(year, B)
    if not law_ok(B, ['cvf:' + r['id']], [dd], [r.get('title')]): return None
    return {'id': 'cvf:' + r['id'], 'cvf': r['id'], 'doi': None, 'title': r.get('title'), 'year': str(year), 'date': d or str(year), 'journal': f'{conf[:-4]} {year}',
            'venue': 'CVF open access', 'type': 'proceedings', 'url': f"{CVF}{r['id']}.html", 'version_note': 'open-access version provided by CVF (identical to the accepted paper except the watermark)'}


def proc_sources(B):
    """Volumes searched: PMLR = the newest volume published < T of each of the first cs_engines.pmlr_volumes venues of PMLR_VENUES (at most
    two feeds tried per venue); CVF = the cs_engines.cvf_conferences newest main conferences published < T (undated: of a year < year of T);
    ACL Anthology entirely (one index)."""
    pv, vols = [], pmlr_volumes()
    for ven in PMLR_VENUES[:int(CS.get('pmlr_volumes', 6))]:
        for v, vv, y in [x for x in vols if x[1] == ven and x[2] <= B.T.year][:2]:
            d = pmlr_volume(v).get('date')
            if (d and _before(d, B)) or (not d and y < B.T.year): pv.append((v, ven, y)); break
    cv = [x for x in cvf_confs() if (x[2] and _before(x[2], B)) or (not x[2] and x[1] < B.T.year)][:int(CS.get('cvf_conferences', 2))]
    return pv, cv


def search_proceedings(q, n, B):
    """Local title search over the ACL Anthology, recent PMLR volumes and CVF conferences (proc_sources); every query word in the title
    (PMLR: or the abstract); most title words first, then most recent; ACL DOIs rechecked on Crossref."""
    if not tokens(q): return [], 'no usable word (3 letters or more)'
    pv, cv = proc_sources(B); hits = []
    for s, r in cs_match(q, acl_index(), lambda r: ''): hits.append((s, str(date_upper(f"{r.get('year')} {r.get('month') or ''}".strip()) or ''), 'acl', r, None))
    for v, ven, y in pv:
        vol = pmlr_volume(v)
        hits += [(s, vol.get('date') or str(y), 'pmlr', r, (vol, y)) for s, r in cs_match(q, vol['papers'], lambda r: r.get('abstract') or '')]
    for c, y, d in cv: hits += [(s, d or str(y), 'cvf', r, (c, y, d)) for s, r in cs_match(q, cvf_papers(c), lambda r: '')]
    hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
    out, cand, rounds = [], [], 0
    for i, (s, _, k, r, ctx) in enumerate(hits):                          # Crossref recheck by chunks of 2n candidates, at most 4 rounds
        x = acl_item(r, B) if k == 'acl' else pmlr_item(r, ctx[0], ctx[1], B) if k == 'pmlr' else cvf_item(r, *ctx, B)
        if x: cand.append(x)
        if len(cand) >= 2 * n or (i == len(hits) - 1 and cand):
            out += doi_recheck(cand, B); cand = []; rounds += 1
            if len(out) >= n or rounds >= 4: break
    out = out[:n]
    return out, (f"{len(hits)} title matches, all dates (ACL Anthology all volumes; PMLR {', '.join(f'{v} {ven} {y}' for v, ven, y in pv) or 'none'}; "
                 f"CVF {', '.join(c for c, _, _ in cv) or 'none'}), local index")


def cit_meta(page):
    """Highwire citation_* meta tags -> {name: first value} (the first citation_author is the first author)."""
    out = {}
    for k, v in re.findall(r'<meta name="citation_([a-z_]+)" content="([^"]*)"', page): out.setdefault(k, v)
    return out


def read_proceedings(p, v, B):
    v = v.strip()
    if p == 'acl':
        if not re.fullmatch(r'[A-Za-z0-9][\w.-]{2,40}', v) or '..' in v: return {'refusal': 'expected form acl:<Anthology id>, e.g. acl:2024.acl-long.1'}
        try: es = bib_entries(fetch(f'{ACL}{v}.bib').decode('utf-8', 'replace'))
        except urllib.error.HTTPError as e:
            if http_code(e) in (404, 410): return {'refusal': 'not found'}
            raise
        it = acl_item(dict(acl_rec(es[0]), id=v), B) if es else None
        if not it or not doi_recheck([it], B): return {'refusal': 'not found, after T, forbidden or deposit not attested'}
        m = re.search(r'(?s)acl-abstract.*?<span>(.*?)</span>', fetch(f'{ACL}{v}/').decode('utf-8', 'replace'))
        return dict(it, abstract=cs_text(m.group(1)) if m else '(no abstract on the Anthology page)', full_text='PDF only (not parsed)')
    if p == 'pmlr':
        if not re.fullmatch(r'v\d+/[\w.-]+', v) or '..' in v: return {'refusal': 'expected form pmlr:v<volume>/<paper key>, e.g. pmlr:v202/aamand23a'}
        try: page = fetch(f'{PMLR}{v}.html').decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            if http_code(e) in (404, 410): return {'refusal': 'not found'}
            raise
        meta = cit_meta(page)
        d = (meta.get('publication_date') or '').replace('/', '-')
        if not law_ok(B, ['pmlr:' + v], [d or None], [meta.get('title')]): return {'refusal': 'after T, forbidden or undated'}
        m = re.search(r'(?s)<div id="abstract"[^>]*>(.*?)</div>', page)
        return {'id': 'pmlr:' + v, 'pmlr': v, 'doi': None, 'title': html.unescape(meta.get('title') or ''), 'year': d[:4], 'date': d, 'venue': 'PMLR',
                'journal': html.unescape(meta.get('conference_title') or meta.get('journal_title') or ''), 'type': 'proceedings',
                'first_author': html.unescape(meta.get('author') or '') or None, 'url': f'{PMLR}{v}.html', 'abstract': cs_text(m.group(1)) if m else '(no abstract)', 'full_text': 'PDF only (not parsed)'}
    if not re.fullmatch(r'content[\w/.-]+_paper', v) or '..' in v: return {'refusal': 'expected form cvf:<path of the paper page>, e.g. cvf:content/CVPR2024/html/<Name>_CVPR_2024_paper'}
    cm = re.match(r'content[_/]((?:CVPR|ICCV|WACV))_?(\d{4})', v)
    if not cm: return {'refusal': 'unknown CVF conference in the path'}
    conf, y = cm.group(1) + cm.group(2), int(cm.group(2))
    d = next((x[2] for x in cvf_confs() if x[0] == conf), None)
    try: page = fetch(f'{CVF}{v}.html').decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        if http_code(e) in (404, 410): return {'refusal': 'not found'}
        raise
    meta = cit_meta(page)
    it = cvf_item({'id': v, 'title': html.unescape(meta.get('title') or '')}, conf, y, d, B)
    if not it: return {'refusal': 'after T or forbidden'}
    m = re.search(r'(?s)<div id="abstract"[^>]*>(.*?)</div>', page)
    return dict(it, first_author=html.unescape(meta.get('author') or '') or None, abstract=cs_text(m.group(1)) if m else '(no abstract)', full_text='PDF only (not parsed)')


def read_cs(ident, B):
    p, _, v = ident.partition(':'); p = p.lower()
    if p in HF_KIND: return read_hf(p, v.strip(), B)
    if p in ('rfc', 'pep', 'w3c'): return read_standard(p, v, B)
    return read_proceedings(p, v, B)


# ---- related works (OpenAlex related_works of a work; same barrier as citing/references)

def related(ident, n, B):
    """OpenAlex related_works of a work dated < T (arXiv: v1 < T; other: OpenAlex publication date < T); each related work rechecked like an
    OpenAlex search result (publication < T, then Crossref deposit AND publication < T; no Crossref DOI -> refused)."""
    s = ident.strip().lower()
    if s.startswith(CS_PREFIX + EXTRA_PREFIX + LAW_PREFIX + B3_PREFIX): return [], 'related works served only for doi:, pmid:, arxiv: or OpenAlex W identifiers'
    r = rxiv_ident(ident)
    if r and 'refusal' in read_rxiv(r[0], r[1], B, published=False): return [], 'document after T, forbidden or not found'
    if s.startswith('arxiv:'):
        if not _arxiv_ok(ident, B): return [], 'document after T or forbidden'
    w = oa_work('doi:' + r[1] if r else ident.strip())
    if not s.startswith('arxiv:') and not r and not oa_item(w, B): return [], 'document after T or forbidden'
    out, tot = _references_openalex({'referenced_works': w.get('related_works') or []}, n, B)
    return out[:n], f'{tot} related works in OpenAlex (all dates), {len(out)} before T (Crossref recheck)'


_read_rx, _citing_rx, _references_rx = read, citing, references


def read(ident, B):
    return read_cs(ident.strip(), B) if ident.strip().lower().startswith(CS_PREFIX) else _read_rx(ident, B)


def citing(ident, n, B):
    if ident.strip().lower().startswith(CS_PREFIX): return [], 'citation chaining not served for hfmodel:, hfdataset:, rfc:, pep:, w3c:, acl:, pmlr:, cvf: identifiers (read the DOI or arXiv id)'
    return _citing_rx(ident, n, B)


def references(ident, n, B):
    if ident.strip().lower().startswith(CS_PREFIX): return [], 'citation chaining not served for hfmodel:, hfdataset:, rfc:, pep:, w3c:, acl:, pmlr:, cvf: identifiers (read the DOI or arXiv id)'
    return _references_rx(ident, n, B)


ENGINES.update({'hf-models': search_hf_models, 'hf-datasets': search_hf_datasets, 'standards': search_standards, 'proceedings': search_proceedings})


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
INTERVAL.update({'oauth.piste.gouv.fr': 1.0, 'api.piste.gouv.fr': 2.0})   # law.md 5: 2 s local; published quota not established
FILTER_OPT = {'search-justice-administrative': ('court', 'date_from', 'date_to'), 'search-judilibre': ('court', 'chamber', 'date_from', 'date_to'),
              'search-legifrance': ('fund',)}                                 # options passed by Gateway.call to each engine
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


_read_cs, _citing_cs, _references_cs, _related_cs = read, citing, references, related
PISTE_NO_CHAIN = 'citation chaining not served for judilibre:, legi:, jorf: identifiers'


def read(ident, B): return read_piste(ident.strip(), B) if ident.strip().lower().startswith(PISTE_PREFIX) else _read_cs(ident, B)
def citing(ident, n, B): return ([], PISTE_NO_CHAIN) if ident.strip().lower().startswith(PISTE_PREFIX) else _citing_cs(ident, n, B)
def references(ident, n, B): return ([], PISTE_NO_CHAIN) if ident.strip().lower().startswith(PISTE_PREFIX) else _references_cs(ident, n, B)
def related(ident, n, B): return ([], PISTE_NO_CHAIN) if ident.strip().lower().startswith(PISTE_PREFIX) else _related_cs(ident, n, B)


ENGINES.update({'judilibre': search_judilibre, 'legifrance': search_legifrance})   # registry of the PISTE engines


# ---------------------------------------------------------------- plugins and interface

def read_plugin(path):
    """Reads the ```sources block of a plugin (key: value lines). Without block: no engine declared (reported)."""
    txt = pathlib.Path(path).read_text(encoding='utf-8')
    m = re.search(r'```sources[^\n]*\n(.*?)```', txt, re.S)
    decl = {}
    if m:
        for line in m.group(1).splitlines():
            line = line.split('#', 1)[0].strip()
            if ':' in line:
                k, v = line.split(':', 1); decl[k.strip().lower()] = v.strip()
    engines = [x.lower() for x in re.split(r'[,\s]+', decl.get('engines', '')) if x]
    code = [x for x in engines if x in CODE_ENGINES.values()]                 # declared code engines, listed apart (code_engines)
    keys = [x for x in re.split(r'[,\s]+', decl.get('keys', '')) if x]
    return {'file': str(path), 'name': pathlib.Path(path).stem, 'declared': bool(m), 'engines': [x for x in engines if x not in code], 'code_engines': code,
            'since': decl.get('since') or None, 'cap': int(decl['cap']) if decl.get('cap', '').isdigit() else None, 'keys': keys}


class Gateway:
    def __init__(self, plugins=(), T=None, case=None, run='vp', state=None, cap=None, since=None):
        global STATE
        self.plugins = [read_plugin(p) for p in plugins]
        if case: self.B = Barrier.from_case(case)
        else:
            low = since or min((int(p['since']) for p in self.plugins if p['since'] and str(p['since']).isdigit()), default=None)
            self.B = Barrier(T or dt.date.today(), since=low)
        declared = [m for p in self.plugins for m in p['engines']]
        self.engines = sorted(set(declared) & set(ENGINES)) if self.plugins else sorted(ENGINES)
        self.code_engines = sorted({m for p in self.plugins for m in p['code_engines']})   # absent without plugin (intended difference)
        self.served_by = {m: SERVED_BY[m] for m in sorted(set(declared) - set(ENGINES)) if SERVED_BY.get(m) in self.code_engines}
        self.not_wired = sorted(set(declared) - set(ENGINES) - set(self.served_by))   # a name served by a declared code engine is not "not wired"
        self.cap = cap or min((p['cap'] for p in self.plugins if p['cap']), default=None) or CFG['call_cap']['default']
        self.run = re.sub(r'[^A-Za-z0-9_.-]', '_', str(run))
        STATE = pathlib.Path(state or os.environ.get('VP_STATE') or 'vp-state')
        self.state = STATE
        self.client = sc.CodeClient(cache_dir=self.state)                     # receipts in <state>/requests.jsonl, never the URL nor the token

    def sources(self):
        return {'T': self.B.T.isoformat(), 'bound': f'documents before {self.B.T}', 'since': self.B.since, 'cap': self.cap,
                'engines': self.engines, 'not_wired': self.not_wired, 'served_by': self.served_by, 'code_engines': self.code_engines,
                'keys_present': sorted({k for p in self.plugins for k in p['keys'] if live_key(k)} | self._github_state()),
                'key_invalid': sorted(sc.invalid_keys(self.state)),
                'commands': ['search-' + m for m in self.engines] + ['read', 'citing', 'references', 'related'] + [c for c, m in CODE_ENGINES.items() if m in self.code_engines],
                'plugins': [{'name': p['name'], 'file': p['file'], 'sources_block': p['declared']} for p in self.plugins]}

    def _github_state(self):
        if 'code' not in self.code_engines: return set()
        try: return {'GITHUB'} if sc.read_token() else set()
        except ValueError: return {'GITHUB: invalid (credential_invalid, KEYS.md)'}

    def _count(self):
        self.state.mkdir(parents=True, exist_ok=True)
        with open(self.state / f'counter-{self.run}.txt', 'a+') as f:
            fcntl.flock(f, fcntl.LOCK_EX); f.seek(0); k = int(f.read() or 0)
            if k >= self.cap: return None
            f.seek(0); f.truncate(); f.write(str(k + 1))
        return k + 1

    def call(self, cmd, arg, n=20, **opt):
        """One counted and journaled command. opt: language, repo (search-code); court, date_from, date_to (search-justice-administrative)."""
        if cmd == 'sources': return self.sources()
        n = max(1, min(int(n), 100 if cmd in ('citing', 'references', 'related') else 50))
        if cmd in CODE_ENGINES and CODE_ENGINES[cmd] not in self.code_engines:
            return {'refusal': f"engine '{CODE_ENGINES[cmd]}' not declared by the plugins (sources block); available code engines: {', '.join(self.code_engines) or 'none'}"}
        if cmd == 'versions' and not re.fullmatch(VERSION_FORM, arg):
            return {'refusal': VERSION_FORM_MSG}
        if cmd == 'provenance' and not re.fullmatch(f'{sc.ORIGIN}|{sc.SWHID}', arg):
            return {'refusal': ORIGIN_FORM_MSG}
        if cmd == 'vulns' and not re.fullmatch(sc.OSV_FORM, arg): return {'refusal': OSV_FORM_MSG}
        if cmd == 'read' and arg.strip().lower().startswith('osv:') and 'osv' not in self.code_engines:
            return {'refusal': "engine 'osv' not declared by the plugins (sources block); available code engines: " + (', '.join(self.code_engines) or 'none')}
        if cmd.startswith('search-') and cmd[7:] not in self.engines and cmd not in CODE_ENGINES:
            return {'refusal': f"engine '{cmd[7:]}' not declared by the plugins (sources block) or not wired; available engines: {', '.join(self.engines)}"}
        if not (cmd.startswith('search-') or cmd in ('read', 'citing', 'references', 'related') or cmd in CODE_ENGINES):
            return {'refusal': f"unknown command '{cmd}'"}
        k = self._count()
        if k is None:
            return {'refusal': f"CAP reached ({self.cap} calls): stop searching and return your list."}
        B = self.B; B.excluded = 0; err = None; extra = {}
        ja_opt = {k: opt[k] for k in FILTER_OPT.get(cmd, ()) if opt.get(k)}   # engine filters (FILTER_OPT, PISTE block)
        if ja_opt: extra['filters'] = ja_opt
        engine = CODE_ENGINES.get(cmd) or (cmd[7:] if cmd.startswith('search-') else None)
        try:
            if cmd in CODE_ENGINES: res, total = self._code(cmd, arg, n, opt, B, extra), None
            elif cmd == 'read' and arg.strip().lower().startswith('osv:'): res, total = read_osv(arg.strip()[4:].strip(), self.client, B), None
            elif cmd == 'read': res, total = read(arg, B), None
            else:
                fn = ENGINES[cmd[7:]] if cmd.startswith('search-') else {'citing': citing, 'references': references, 'related': related}[cmd]
                res, total = fn(arg, n, B, **ja_opt) if ja_opt else fn(arg, n, B)
        except Exception as e:
            res, total, err = {'error': f'{type(e).__name__}: {str(e)[:200]}'}, None, str(e)
        inv = sorted(sc.invalid_keys(self.state))                            # names of the keys rejected by their provider in this run
        out = {'call': k, 'cap': self.cap, 'bound': f'documents before {B.T}', 'index_total': total,
               'excluded_post_T_or_forbidden': B.excluded, 'results': res, 'engine': engine, 'query': arg, 'n': n, **extra, **({'key_invalid': inv} if inv else {})}
        with open(self.state / 'journal.jsonl', 'a') as f:
            f.write(json.dumps({'utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'run': self.run, 'T': B.T.isoformat(), 'call': cmd, 'engine': engine,
                                'query': arg, **({'filters': ja_opt} if ja_opt else {}), 'n': n, 'count': len(res) if isinstance(res, list) else None, 'excluded': B.excluded, 'error': err, **({'key_invalid': inv} if inv else {}),
                                'ids': [r.get('id') for r in res] if isinstance(res, list) else [res.get('id')] if isinstance(res, dict) else []},
                               ensure_ascii=False) + '\n')
        return out

    def _code(self, cmd, arg, n, opt, B, extra):
        """Code engines (code_sources.py): same counter, same journal, same envelope; date barrier by _date_filter."""
        c = self.client
        if cmd == 'vulns': return osv_vulns(c, arg, n, B)                    # barrier inside (osv_item): published < T, post-T edits masked
        if cmd in B3_CODE: return B3_CODE[cmd](self, arg, n, opt, B, extra)
        if cmd == 'search-code':
            cs = sc.CodeSearch(c); f = dict(language=opt.get('language'), repo=opt.get('repo'), limit=n)
            res = cs.search(arg, 'sourcegraph', **f)
            try: gh = cs.search(arg, 'github', **f)                           # GitHub only with a token, else skipped; its typed error does not lose Sourcegraph
            except ValueError as e: gh = {'status': 'error', 'reason': str(e)}
            if isinstance(gh, dict): extra['github'] = gh
            else: res += gh
        elif cmd == 'versions':
            s, p, v = re.fullmatch(VERSION_FORM, arg).groups(); vs = sc.Versions(c)
            m, d = vs.metadata(s, p, v), vs.deps(s, p, v)                       # date = publishedAt of deps.dev, else the registry date
            res = dict(m, date=d['date'] or m['date'], date_registry=m['date'], date_deps_dev=d['date'], graph=d['dependencies'], edges=d['edges'], advisories=d['advisories'])
        elif cmd == 'paper-code': res = sc.PaperCode(c).search(arg, limit=n)
        else: res = sc.Provenance(c).resolve(arg) if arg.startswith('swh:1:') else sc.Provenance(c).visit(arg)
        res = self._date_filter(res, B, extra)
        return res if res is not None else {'refusal': 'after T'}

    def _date_filter(self, x, B, extra):
        """Date barrier of the code engines: dated >= T removed and counted (Barrier.ok); undated kept with dating "absent"."""
        if isinstance(x, list): return [y for y in (self._date_filter(i, B, extra) for i in x) if y is not None]
        if not isinstance(x, dict): return x
        dates = [x[k] for k in ('date', 'date_visited', 'date_registry', 'date_deps_dev') if x.get(k)]   # every date carried
        if not dates: x['dating'] = 'absent'; extra['warning'] = 'live index: results cannot be dated'
        elif not B.ok(None, *dates): return None
        for k in ('repos', 'models', 'datasets', 'spaces'):
            if k in x: x[k] = self._date_filter(x[k], B, extra)
        return x

    def search(self, engine, q, n=20, **opt): return self.call('search-' + engine, q, n, **opt)
    def read(self, ident): return self.call('read', ident)
    def citing(self, ident, n=25): return self.call('citing', ident, n)
    def references(self, ident, n=50): return self.call('references', ident, n)
    def related(self, ident, n=25): return self.call('related', ident, n)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plugin', action='append', default=[], help='plugin file (repeatable)')
    ap.add_argument('--T', help='date of the question YYYY-MM-DD (default: today)')
    ap.add_argument('--case', help='date-barrier case id from tests/fixtures/bench_cases.json (tests only: fixes T, forbidden DOIs and titles)')
    ap.add_argument('--run', default='vp'); ap.add_argument('--state', default=None); ap.add_argument('--cap', type=int, default=None)
    ap.add_argument('--since', default=None)
    ap.add_argument('cmd'); ap.add_argument('arg', nargs='*'); ap.add_argument('--n', type=int, default=20)
    ap.add_argument('--language', default=None); ap.add_argument('--repo', default=None, help='search-code: language / owner/repo filters')
    ap.add_argument('--court', default=None, help='search-justice-administrative: exact court code (CE, TA75, CAA69)')
    ap.add_argument('--from', dest='date_from', default=None); ap.add_argument('--to', dest='date_to', default=None, help='search-justice-administrative: decision-date window YYYY-MM-DD')
    ap.add_argument('--chamber', default=None, help='search-judilibre: chamber key (civ1, soc, cr...); --court cc|ca|tj|tcom'); ap.add_argument('--fund', default=None, help='search-legifrance: code|loda|jorf')
    a = ap.parse_args()
    g = Gateway(a.plugin, T=a.T, case=a.case, run=a.run, state=a.state, cap=a.cap, since=a.since)
    print(json.dumps(g.call(a.cmd, ' '.join(a.arg), a.n, language=a.language, repo=a.repo, court=a.court, date_from=a.date_from, date_to=a.date_to, chamber=a.chamber, fund=a.fund), ensure_ascii=False))


if __name__ == '__main__':
    main()
