"""Lacuna (Tiptree Systems research map of machine learning): search-lacuna, read lacuna:<artifact id>. Optional, keyless, ML/AI only.

Papers are an INDEX lane (tier 'index', never a primary source): every paper is served under its DOI or arXiv identifier when Lacuna
records one (deduplicated against the other engines on that identifier, and rechecked: Crossref deposit AND publication < T for a DOI,
arXiv record for an arXiv id), else as lacuna:<artifact id> with the dblp key / OpenReview forum it carries.

Research directions (clusters) and generated research hypotheses ("The Alien Space of Science", arXiv 2603.01092) are leads, never
evidence: served only with the explicit option `generated` (gateway.py search-lacuna "<q>" --generated direction|hypothesis), each marked
type 'generated_hypothesis', evidence False, identifier lacunaidea:<kind>/<id> (not a card / result.json identifier: never citable).
They have no publication date in the sense of T: they are derived from Lacuna's CURRENT corpus (papers after T included) or generated
after it was built, so their mere wording can leak post-T knowledge (leak_risk on every item)."""
import re
import urllib.parse
from sources._common import CFG, arxiv_id, arxiv_month, extra_ok, jget, title_sim, tokens, value, year_before_T
from sources.crossref import crossref_deposit

LC = CFG['lacuna']
API = LC['api'].rstrip('/') + '/'
HOST = urllib.parse.urlparse(API).netloc
SITE = f'{urllib.parse.urlparse(API).scheme}://{HOST}'
KINDS = {'direction': 'cluster', 'hypothesis': 'hypothesis'}   # option value -> search type of the API (the MCP maps direction -> cluster)
LEAK = ('derived from the current Lacuna corpus or generated after it was built (no date before T): a lead to search, never evidence; '
        'its wording may reflect work published on/after T')
NO_CHAIN = 'citation chaining not served for lacuna: identifiers (read the DOI or arXiv identifier, or the dblp key)'


def lc_dates(r):
    """Dates of a Lacuna paper record, each passed to the barrier. date_precision 'year' (Lacuna writes YYYY-01-01) -> the year only,
    kept when strictly before the year of T (year_before_T); 'month' -> YYYY-MM (upper bound); no precision given and a 1 January date ->
    read as a year (no fabricated precision). No date at all -> [] (refused). Every OTHER year Lacuna lists (year, info.years: versions,
    venues) is checked too, as a year; the year of the publication date itself is covered by that date at its precision."""
    d, prec = str(r.get('published_date') or '').strip(), str(r.get('date_precision') or '').lower()
    out = []
    if re.match(r'\d{4}', d):
        if prec == 'year' or (not prec and re.fullmatch(r'\d{4}(-01-01)?', d)): out.append(('Y', d[:4]))
        elif prec == 'month': out.append(('D', d[:7]))
        else: out.append(('D', d[:10]))
    if not out: return []                                                   # a bare year field without a publication date is not enough
    years = [r.get('year')] + list((r.get('info') or {}).get('years') or [])
    return out + [('Y', str(y)) for y in dict.fromkeys(years) if re.fullmatch(r'\d{4}', str(y or '')) and str(y) != d[:4]]


def lc_ids(r):
    """(doi, arXiv id, dblp key, OpenReview forum) of a record (search result `identifiers`, or `info` of a paper record).
    An arXiv DOI or an arxiv.org PDF link names the arXiv id; it is never kept as a DOI (no Crossref deposit exists for it)."""
    i = dict(r.get('info') or {}, **(r.get('identifiers') or {}))
    doi = str(i.get('doi') or '').strip() or None
    ax = arxiv_id('arxiv:' + str(i['arxiv_id'])) if i.get('arxiv_id') else None
    ax = ax or (arxiv_id(doi) if doi else None)
    for u in [i.get('pdf_url')] + list(i.get('pdf_urls') or []):
        ax = ax or arxiv_id(u)
    if doi and arxiv_id(doi): doi = None
    orv = re.search(r'[?&]id=([\w-]+)', str(i.get('openreview_url') or '')) or next(
        (m for u in i.get('source_urls') or [] for m in [re.search(r'openreview\.net/forum\?id=([\w-]+)', str(u))] if m), None)
    return doi, ax, i.get('dblp_key') or None, orv.group(1) if orv else None


def lc_url(x):
    u = str(x.get('url') or '')
    return SITE + u if u.startswith('/') else (u or None)


def lc_item(r, B):
    """A paper record under the local barrier, or None (counted in B.excluded). Forbidden as any of its identifiers or by its title;
    every date (publication at its precision, listed years, month of v1 of the arXiv id) < T; no usable date -> refused."""
    aid = r.get('artifact_id') or r.get('id')
    title = ' '.join(str(r.get('title') or '').split())
    doi, ax, dblp, orv = lc_ids(r)
    dates = [year_before_T(v, B) if k == 'Y' else v for k, v in lc_dates(r)]
    if dates and ax: dates.append(arxiv_month(ax))
    ids = [doi, aid, 'lacuna:' + str(aid)] + (['arxiv:' + ax, ax] if ax else [])
    if not aid or not title or not extra_ok(B, ids, dates or [None], [title]): return None
    it = {'id': f'arxiv:{ax}' if ax else f'doi:{doi}' if doi else f'lacuna:{aid}', 'lacuna': aid, 'title': title,
          'year': r.get('year'), 'journal': r.get('venue') or r.get('conference'), 'type': 'paper', 'tier': 'index', 'url': lc_url(r)}
    if ax: it['arxiv'] = ax
    if doi: it['doi'] = doi
    if dblp: it['dblp'] = dblp
    if orv: it['openreview'] = orv
    return it


def lc_recheck(items, B):
    """DOI items: Crossref deposit AND publication < T; arXiv items: arXiv record (no forbidden venue DOI nor title); both through
    crossref_deposit (strict: not attested -> refused, counted). lacuna: items (no DOI, no arXiv id) were dated locally and are kept."""
    ext = [x for x in items if x['id'].startswith(('doi:', 'arxiv:'))]
    ok = {id(x) for x in crossref_deposit(ext, B)} if ext else set()
    return [x for x in items if id(x) in ok or x['id'].startswith('lacuna:')]


def lc_search(params):
    return jget(API + 'search?' + urllib.parse.urlencode(params))


def search_lacuna(q, n, B, generated=None):
    """Papers (type=paper) bounded on the provider side (date_to = eve of T, date_from = start with since; Lacuna stores year-precision
    papers on 1 January, so the local recheck is what decides), then the local barrier and the DOI/arXiv recheck, paging until n pass
    (at most lacuna.extra_pages pages beyond the first). generated='direction'|'hypothesis': leads instead of papers (module docstring)."""
    if generated: return search_generated(q, n, B, generated)
    if not str(q or '').strip(): return [], 'empty query'
    size = max(1, min(int(LC['page_max']), n))
    base = {'q': q, 'type': 'paper', 'limit': size, 'sort': 'relevance', 'ranking_profile': 'default', 'date_to': B.eve.isoformat()}
    if B.since: base['date_from'] = B.start.isoformat()
    out, seen, total = [], set(), None
    for page in range(1 + max(0, int(LC['extra_pages']))):
        r = lc_search(dict(base, offset=page * size))
        total = r.get('total_results') if total is None else total
        rows = [x for x in r.get('results') or [] if x.get('type') == 'paper']
        for x in lc_recheck([y for y in (lc_item(z, B) for z in rows) if y], B):
            if x['id'] not in seen: seen.add(x['id']); out.append(x)
        if len(out) >= n or len(r.get('results') or []) < size or (total is not None and (page + 1) * size >= total): break
    return out[:n], total


def search_generated(q, n, B, kind):
    """Research directions or generated hypotheses: leads only (type generated_hypothesis, evidence False, undated, never citable).
    Forbidden titles still apply; no date barrier is possible (none exists before T), hence the explicit option and leak_risk."""
    k = str(kind).strip().lower()
    if k not in KINDS: return {'refusal': f"generated: expected one of {', '.join(KINDS)}"}, None
    if not str(q or '').strip(): return [], 'empty query'
    r = lc_search({'q': q, 'type': KINDS[k], 'limit': max(1, min(int(LC['generated_max']), n)), 'offset': 0, 'sort': 'relevance',
                   'ranking_profile': 'default'})
    out = []
    for x in r.get('results') or []:
        t = ' '.join(str(x.get('title') or '').split())
        if not x.get('id') or not t or x.get('type') != KINDS[k]: continue
        if any(title_sim(tokens(t), f) >= CFG['review_title_threshold'] for f in B.titles): B.excluded += 1; continue
        out.append({'id': f"lacunaidea:{k}/{x['id']}", 'title': t, 'type': 'generated_hypothesis', 'kind': k, 'evidence': False, 'tier': 'index',
                    'dating': 'absent', 'leak_risk': LEAK, 'url': lc_url(x), **({'n_papers': x['n_papers']} if isinstance(x.get('n_papers'), int) else {})})
    return out, r.get('total_results')


def read_lacuna(ident, B):
    """lacuna:<artifact id> -> metadata and abstract of the paper record (same barrier as the search; a DOI or arXiv id it carries is
    rechecked). Lacuna's generated summary is never served. Refusal: bad form, not found, after T, forbidden or not attested."""
    if ident.strip().lower().startswith('lacunaidea:'):
        return {'refusal': 'lacunaidea: is a generated research direction or hypothesis (a lead, never evidence): not a document, never read nor cited'}
    aid = value(ident)
    if not re.fullmatch(r'art_[0-9a-f]{8,64}', aid): return {'refusal': 'expected form lacuna:art_<hex> (artifact id of a Lacuna paper)'}
    try: r = jget(API + 'papers/' + aid)
    except Exception: return {'refusal': 'not found'}
    if not isinstance(r, dict): return {'refusal': 'not found'}
    r = dict(r, artifact_id=aid, venue=r.get('venue') or r.get('conference'))
    it = lc_item(r, B)
    it = (lc_recheck([it], B) or [None])[0] if it else None
    if not it: return {'refusal': 'after T, forbidden, undated or identifier not attested before T'}
    return dict(it, abstract=' '.join(str(r.get('abstract') or '(no abstract available)').split())[:6000])


SOURCE = {
    'name': 'lacuna', 'order': 120,
    'engines': {'lacuna': {'search': search_lacuna, 'options': ('generated',)}},
    'ids': [{'prefix': 'lacuna', 'form': r'art_[0-9a-f]{8,64}', 'export': 'paper', 'export_rank': 120},
            {'prefix': 'lacunaidea', 'card': False}],   # generated leads: no form, not a card field -> never citable; read -> refusal
    'read': read_lacuna, 'citing': NO_CHAIN, 'references': NO_CHAIN, 'related': NO_CHAIN,
    'plugins': ('cs-ai',), 'access': 'api',
    'hosts': {HOST: {'interval': max(1.0, float(LC['interval_s'])), 'stop': (401, 403, 429)}},
    'terms': 'Lacuna public API (OpenAPI /openapi.json; llms.txt: public corpus search needs no key), keyless; robots.txt Disallow /api/v1/ '
             'addresses crawlers and has no effect on a documented API (ACCESS-POLICY.md level 1); client package lacuna-research-mcp MIT',
    'barrier': 'provider side: date_to = eve of T (date_from with since); local: published_date at its precision (year precision -> year < year of T), '
               'every listed year and the month of v1 of an arXiv id < T; DOIs rechecked on Crossref, arXiv ids on arXiv; generated directions and '
               'hypotheses are undated: served only with --generated, marked evidence False and leak_risk, never citable',
}
