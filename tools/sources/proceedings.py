# SPDX-License-Identifier: Apache-2.0
"""Conference proceedings (keyless): search-proceedings over the ACL Anthology, recent PMLR volumes and CVF conferences (local title
index); read acl:<id> | pmlr:v<vol>/<key> | cvf:content/<CONF>/html/<name>_paper."""
import xml.etree.ElementTree as ET
import datetime as dt
import html
import re
import urllib.error, urllib.parse, urllib.request
from sources._common import _before, date_upper, fetch, http_code, law_ok, tokens, year_before_T
from sources._cs import CS, cs_index, cs_match, cs_text
from sources.crossref import doi_recheck
from sources._common import RELATED_ONLY
from sources._cs import CS_NO_CHAIN, CS_STOP


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


def read_proceedings_ident(ident, B):
    p, _, v = ident.partition(':')
    return read_proceedings(p.lower(), v, B)


SOURCE = {
    'name': 'proceedings', 'order': 180,
    'engines': {'proceedings': search_proceedings},
    'ids': [{'prefix': 'acl', 'form': r'[A-Za-z0-9][\w.-]+', 'export': 'paper', 'export_rank': 90},
            {'prefix': 'pmlr', 'form': r'v\d+/[\w.-]+', 'export': 'paper', 'export_rank': 90},
            {'prefix': 'cvf', 'form': r'content[\w/.-]+_paper', 'export': 'paper', 'export_rank': 90}],
    'read': read_proceedings_ident, 'citing': CS_NO_CHAIN, 'references': CS_NO_CHAIN, 'related': RELATED_ONLY,
    'plugins': ('cs-ai',), 'access': 'page',
    'hosts': {'aclanthology.org': {'interval': 2.0, 'stop': CS_STOP}, 'proceedings.mlr.press': {'interval': 2.0, 'stop': CS_STOP},
              'openaccess.thecvf.com': {'interval': 2.0, 'stop': CS_STOP}},
    'terms': 'ACL Anthology, PMLR and CVF open access pages: public, keyless; index files fetched once per run',
    'barrier': 'local: conference date (or year strictly before the year of T) < T; ACL DOIs rechecked on Crossref; volumes and conferences listed only when dated < T',
}
