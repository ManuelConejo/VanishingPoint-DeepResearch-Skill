#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Dated gateway of VanishingPoint (non-leak measured on our benches: 19/19 cases).
The only document access of the engine. Refuses every document dated >= T (publication AND indexing when available),
the forbidden DOIs and titles, and the engines that no plugin declared.

Command line:
  gateway.py [--plugin P.md ...] [--T YYYY-MM-DD | --case ID] [--run NAME] [--state DIR] [--cap N] [--since YEAR]
             <command> <argument> [--n N]
  commands: sources | search-<engine> "<query>" | read <id> | citing <id> | references <id>
  wired engines: pubmed, europepmc, crossref, openalex, arxiv   (id: pmid:NNN | doi:10.x | arxiv:2501.01234)
  law engines (plugins/law.md): eurlex, justice-administrative, hal, theses-fr
    (id: celex:32016R0679 | ecli:ECLI:EU:... | ecli:ECLI:FR:... | ja:<court>/<file> | hal:hal-0123 | thesesfr:<nnt>)
  code engines (code_sources.py; served only when a plugin declares them): search-code "<pattern>" [--language L] [--repo owner/repo] |
    versions <pypi|npm|cargo>:<package>@<version> | paper-code <arxiv> | provenance <origin https://... | swh:1:...>
  extra keyless engines: clinicaltrials (biology), dblp (cs-ai), econbiz (finance)   (id: nct:NCT01234567 | dblp:conf/acl/Xiong0LZ24 | econbiz:10011386660);
    code engine osv: vulns <pypi|npm|cargo|go|maven|rubygems|nuget|packagist>:<package>@<version> ; read osv:<id>
  AI engines (plugins/cs-ai.md): openreview, zenodo, hal-info (id: openreview:<forum id> | zenodo:<record id>); code engine usage <pypi|npm|cargo|...>:<package> (ecosyste.ms)
  A key the provider rejects (NCBI 400 "API key invalid", OpenAlex 401/403, Software Heritage 401/403) is dropped for the rest of the run
  (<state>/keys-invalid.json, names only), the call is retried once without it, and every answer carries key_invalid: [NAME].
Import:
  from gateway import Gateway
  g = Gateway(plugins=['plugins/cs-ai.md'], T='2026-10-26', run='q1')
  g.search('openalex', 'query', n=20) ; g.read('doi:...') ; g.citing('pmid:...') ; g.references('arxiv:...')

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
KEY_REJECTED = {'eutils.ncbi.nlm.nih.gov': ('NCBI_API_KEY', (400,), b'api key invalid'), 'api.openalex.org': ('OPENALEX_KEY', (401, 403), b'')}


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
            if rej and code in rej[1] and 'api_key=' in url and rej[2] in (e.read() or b'').lower():   # key rejected: once without it, then key-less
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


def read_celex(celex, B):
    """CELEX notice (dates, validity under the barrier) + start of the official text through Cellar content negotiation (XHTML, EN then FR).
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
        if t: return dict(it, abstract=t[:20000], text_language=lang, text_source='Cellar (official text, start)')
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


def search_justice_administrative(q, n, B):
    """Administrative courts open data (level 2 `page`): JSON back end of the public engine, decision date bounded on the provider side
    (model_searchANDdates, Date_Lecture range ending on the eve of T); several words = OR, exact phrase in quotes, numbers work."""
    qq = ' '.join(q.replace('/', ' ').split())
    if not qq: return [], 'empty query'
    h = _ja_hits(jget(f'{JA}model_searchANDdates/openData/Date_Lecture/{urllib.parse.quote(qq, safe="")}/{B.start}/{B.eve}/100'))
    out = [x for x in (ja_item(i, B) for i in h.get('hits') or []) if x]
    tot = (h.get('total') or {}).get('value') if isinstance(h.get('total'), dict) else h.get('total')
    cov = ', '.join(f'{k} {v}' for k, v in JA_COVERAGE.items())
    return out[:n], f'bounded: provider announces {tot} (false totals, capped at 1,000, 100 per call, most recent first); coverage_from {cov}'


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
    if not m: return {'refusal': 'not an administrative-court ECLI (judicial ECLI: Judilibre, not wired)'}
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
        self.not_wired = sorted(set(declared) - set(ENGINES))
        self.code_engines = sorted({m for p in self.plugins for m in p['code_engines']})   # absent without plugin (intended difference)
        self.cap = cap or min((p['cap'] for p in self.plugins if p['cap']), default=None) or CFG['call_cap']['default']
        self.run = re.sub(r'[^A-Za-z0-9_.-]', '_', str(run))
        STATE = pathlib.Path(state or os.environ.get('VP_STATE') or 'vp-state')
        self.state = STATE
        self.client = sc.CodeClient(cache_dir=self.state)                     # receipts in <state>/requests.jsonl, never the URL nor the token

    def sources(self):
        return {'T': self.B.T.isoformat(), 'bound': f'documents before {self.B.T}', 'since': self.B.since, 'cap': self.cap,
                'engines': self.engines, 'not_wired': self.not_wired, 'code_engines': self.code_engines,
                'keys_present': sorted({k for p in self.plugins for k in p['keys'] if live_key(k)} | self._github_state()),
                'key_invalid': sorted(sc.invalid_keys(self.state)),
                'commands': ['search-' + m for m in self.engines] + ['read', 'citing', 'references'] + [c for c, m in CODE_ENGINES.items() if m in self.code_engines],
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
        """One counted and journaled command. opt: language, repo (search-code)."""
        if cmd == 'sources': return self.sources()
        n = max(1, min(int(n), 100 if cmd in ('citing', 'references') else 50))
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
        if not (cmd.startswith('search-') or cmd in ('read', 'citing', 'references') or cmd in CODE_ENGINES):
            return {'refusal': f"unknown command '{cmd}'"}
        k = self._count()
        if k is None:
            return {'refusal': f"CAP reached ({self.cap} calls): stop searching and return your list."}
        B = self.B; B.excluded = 0; err = None; extra = {}
        engine = CODE_ENGINES.get(cmd) or (cmd[7:] if cmd.startswith('search-') else None)
        try:
            if cmd in CODE_ENGINES: res, total = self._code(cmd, arg, n, opt, B, extra), None
            elif cmd == 'read' and arg.strip().lower().startswith('osv:'): res, total = read_osv(arg.strip()[4:].strip(), self.client, B), None
            elif cmd == 'read': res, total = read(arg, B), None
            else:
                fn = ENGINES[cmd[7:]] if cmd.startswith('search-') else {'citing': citing, 'references': references}[cmd]
                res, total = fn(arg, n, B)
        except Exception as e:
            res, total, err = {'error': f'{type(e).__name__}: {str(e)[:200]}'}, None, str(e)
        inv = sorted(sc.invalid_keys(self.state))                            # names of the keys rejected by their provider in this run
        out = {'call': k, 'cap': self.cap, 'bound': f'documents before {B.T}', 'index_total': total,
               'excluded_post_T_or_forbidden': B.excluded, 'results': res, 'engine': engine, 'query': arg, 'n': n, **extra, **({'key_invalid': inv} if inv else {})}
        with open(self.state / 'journal.jsonl', 'a') as f:
            f.write(json.dumps({'utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'run': self.run, 'T': B.T.isoformat(), 'call': cmd, 'engine': engine,
                                'query': arg, 'n': n, 'count': len(res) if isinstance(res, list) else None, 'excluded': B.excluded, 'error': err, **({'key_invalid': inv} if inv else {}),
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plugin', action='append', default=[], help='plugin file (repeatable)')
    ap.add_argument('--T', help='date of the question YYYY-MM-DD (default: today)')
    ap.add_argument('--case', help='date-barrier case id from tests/fixtures/bench_cases.json (tests only: fixes T, forbidden DOIs and titles)')
    ap.add_argument('--run', default='vp'); ap.add_argument('--state', default=None); ap.add_argument('--cap', type=int, default=None)
    ap.add_argument('--since', default=None)
    ap.add_argument('cmd'); ap.add_argument('arg', nargs='*'); ap.add_argument('--n', type=int, default=20)
    ap.add_argument('--language', default=None); ap.add_argument('--repo', default=None, help='search-code: language / owner/repo filters')
    a = ap.parse_args()
    g = Gateway(a.plugin, T=a.T, case=a.case, run=a.run, state=a.state, cap=a.cap, since=a.since)
    print(json.dumps(g.call(a.cmd, ' '.join(a.arg), a.n, language=a.language, repo=a.repo), ensure_ascii=False))


if __name__ == '__main__':
    main()
