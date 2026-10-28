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
  code engines (code_sources.py; served only when a plugin declares them): search-code "<pattern>" [--language L] [--repo owner/repo] |
    versions <pypi|npm|cargo>:<package>@<version> | paper-code <arxiv> | provenance <origin https://... | swh:1:...>
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
import argparse, datetime as dt, fcntl, hashlib, json, os, pathlib, re, sys, time, urllib.parse, urllib.request
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
            'api.openalex.org': 0.2, 'export.arxiv.org': 3.0}
NS = {'a': 'http://www.w3.org/2005/Atom', 'x': 'http://arxiv.org/schemas/atom', 'os': 'http://a9.com/-/spec/opensearch/1.1/'}


key = sc.key   # single key rule (code_sources.key, KEYS.md): env NAME, then ~/.config/vp/<name lowercase>.key


def ncbi_key():
    """NCBI_API_KEY as an E-utilities `api_key=` parameter (10 req/s instead of 3); '' without a key."""
    k = key('NCBI_API_KEY')
    return '&api_key=' + urllib.parse.quote(k) if k else ''


def interval(host):
    """Seconds between two calls to a host; E-utilities allow 10 req/s with a key (0.11 s) instead of 3 (0.45 s)."""
    if host == 'eutils.ncbi.nlm.nih.gov' and key('NCBI_API_KEY'): return 0.11
    return INTERVAL.get(host, 0.3)


def fetch(url):
    host = urllib.parse.urlparse(url).netloc
    cache = STATE / 'cache' / hashlib.sha256(url.encode()).hexdigest()
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
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                data = r.read()
            cache.parent.mkdir(parents=True, exist_ok=True); cache.write_bytes(data)
            return data
        except Exception as e:
            if attempt == 4 or (host == 'api.openalex.org' and getattr(e, 'code', None) == 429): raise
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
    k = key('OPENALEX_KEY')
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


ENGINES = {'pubmed': search_pubmed, 'europepmc': search_europepmc, 'crossref': search_crossref, 'openalex': search_openalex, 'arxiv': search_arxiv}
CODE_ENGINES = {'search-code': 'code', 'versions': 'versions', 'paper-code': 'paper-code', 'provenance': 'provenance'}  # command -> engine ; never served without plugin
VERSION_FORM = r'(pypi|npm|cargo):(@?[A-Za-z0-9][\w.+-]*(?:/[A-Za-z0-9][\w.+-]*)?)@([A-Za-z0-9][\w.+-]*)'          # package (npm @scope/name allowed) @ version
VERSION_FORM_MSG = 'expected form <pypi|npm|cargo>:<package>@<version>'
ORIGIN_FORM_MSG = 'expected form <origin https://... | swh:1:...>'


def read(ident, B):
    ident = ident.strip()
    if ident.lower().startswith('arxiv:'):
        return read_arxiv(ident, B)
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
                'keys_present': sorted({k for p in self.plugins for k in p['keys'] if key(k)} | self._github_state()),
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
            elif cmd == 'read': res, total = read(arg, B), None
            else:
                fn = ENGINES[cmd[7:]] if cmd.startswith('search-') else {'citing': citing, 'references': references}[cmd]
                res, total = fn(arg, n, B)
        except Exception as e:
            res, total, err = {'error': f'{type(e).__name__}: {str(e)[:200]}'}, None, str(e)
        out = {'call': k, 'cap': self.cap, 'bound': f'documents before {B.T}', 'index_total': total,
               'excluded_post_T_or_forbidden': B.excluded, 'results': res, 'engine': engine, 'query': arg, 'n': n, **extra}
        with open(self.state / 'journal.jsonl', 'a') as f:
            f.write(json.dumps({'utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'run': self.run, 'T': B.T.isoformat(), 'call': cmd, 'engine': engine,
                                'query': arg, 'n': n, 'count': len(res) if isinstance(res, list) else None, 'excluded': B.excluded, 'error': err,
                                'ids': [r.get('id') for r in res] if isinstance(res, list) else [res.get('id')] if isinstance(res, dict) else []},
                               ensure_ascii=False) + '\n')
        return out

    def _code(self, cmd, arg, n, opt, B, extra):
        """Code engines (code_sources.py): same counter, same journal, same envelope; date barrier by _date_filter."""
        c = self.client
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
