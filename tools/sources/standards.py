# SPDX-License-Identifier: Apache-2.0
"""Standards (keyless): search-standards over the RFC index, the PEP index and the W3C list; read rfc:<n> | pep:<n> | w3c:<shortname>."""
import xml.etree.ElementTree as ET
import datetime as dt
import re
import urllib.error, urllib.parse, urllib.request
from sources._common import TEXT_HEAD, _before, date_upper, fetch, http_code, jget, law_ok, tokens
from sources._cs import CS, cs_index, cs_match, cs_text
from sources._common import RELATED_ONLY
from sources._cs import CS_NO_CHAIN, CS_STOP


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


def read_standard_ident(ident, B):
    p, _, v = ident.partition(':')
    return read_standard(p.lower(), v, B)


SOURCE = {
    'name': 'standards', 'order': 170,
    'engines': {'standards': search_standards},
    'ids': [{'prefix': 'rfc', 'form': r'\d{1,5}', 'export': 'standard', 'export_rank': 20},
            {'prefix': 'pep', 'form': r'\d{1,4}', 'export': 'standard', 'export_rank': 20},
            {'prefix': 'w3c', 'form': r'[\w.-]+', 'export': 'standard', 'export_rank': 20}],
    'read': read_standard_ident, 'citing': CS_NO_CHAIN, 'references': CS_NO_CHAIN, 'related': RELATED_ONLY,
    'plugins': ('cs-ai',), 'access': 'api',
    'hosts': {'www.rfc-editor.org': {'interval': 2.0, 'stop': CS_STOP}, 'peps.python.org': {'interval': 2.0, 'stop': CS_STOP},
              'api.w3.org': {'interval': 1.0, 'stop': CS_STOP}, 'www.w3.org': {'interval': 2.0, 'stop': CS_STOP},     # W3C API 6,000 req/10 min (documented)
              'api.github.com': {'interval': 2.0, 'stop': CS_STOP}, 'raw.githubusercontent.com': {'interval': 2.0, 'stop': CS_STOP}},   # PEP text at a commit < T
    'terms': 'RFC Editor index, PEP index (python/peps), W3C API: public, keyless',
    'barrier': 'local: publication / creation date < T; superseding documents listed only when dated < T; PEP text read at the last commit before T',
}
