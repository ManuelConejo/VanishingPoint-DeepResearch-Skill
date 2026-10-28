#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Data export of a run (SKILL.md section 8): the study table and the bibliography in reference-manager formats. Standard library, offline.
studies.csv: one row per study of result.json (id, title, year, the criteria columns: union of the keys met, the six of validate_result
first, confidence, basis, claims citing it in card.json counted per verdicts.json status, `ref` = its [n] in the bibliography);
RFC 4180 (comma, double quotes, CRLF), UTF-8 without BOM; a text cell starting with = + - @ (or tab, CR) gets a leading apostrophe.
references.bib / references.ris / references.json (CSL-JSON): one record per [n] entry of `## Bibliography` of REPORT.md, completed by
card.json (`sources` S<n> = [n]) and result.json (same identifier). Type guessed from the identifier: article, preprint (arxiv, hal, or
openreview without venue), software (`path@SHA`, osv:, a code host URL), dataset (zenodo), legal (celex, ecli, ja), trial (nct), thesis
(thesesfr). Authors, title, year, venue, DOI are taken from these files only, never guessed beyond them: a field not found stays empty;
the URL is the one written in the entry, else the stable link of its doi/pmid/arxiv/pmcid. The VP identifier goes in note (BibTeX),
AN + N1 (RIS), note (CSL). BibTeX keys: author + year + first title word, ASCII, deduplicated by a, b, c in bibliography order.
Usage: export_data.py RUN_DIR [--out DIR]     Exit: 0 written (paths printed); 2 no REPORT.md.
Import: entries(dir) -> [dict]; studies(dir) -> (header, rows); bibtex/ris/csl(entries) -> str."""
import argparse, csv, io, json, pathlib, re, sys, unicodedata
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from export_report import BIB_LINE, IDLINK, _json            # noqa: E402
from validate_card import IDS, sections                     # noqa: E402
from validate_result import CRITERIA                        # noqa: E402

STATUSES = ['FOUND', 'DISTORTED', 'ABSENT', 'INVALID', 'SOURCE-UNAVAILABLE', 'UNVERIFIED']
VPID = re.compile(r'(?<![\w/.-])(' + '|'.join(i for i in IDS if i != 'code') + r'):(\S+)', re.I)
CODE = re.compile(r'`(?:local:)?([^`\s:@]+(?:/[^`\s:@]+)*)(?::(\d+))?@([0-9a-f]{6,40})`', re.I)
URL = re.compile(r'https?://[^\s<>"\'`]+')
YEAR = re.compile(r'(?<![\d.:/-])(1[5-9]\d\d|20\d\d)(?![\d/-])')
PERSON = (re.compile(r'^((?:[a-z]+ )*[A-Z][\w\'’-]+)(?: ((?:[A-Z]\.?-?)+))?$'),       # Family | de Family | Family F. | Family FG
          re.compile(r'^((?:[A-Z]\.-?\s?)+)\s*((?:[a-z]+ )*[A-Z][\w\'’-]+)$'))          # F. Family | F.G. Family
ETAL = re.compile(r',?\s*\bet al\.?$', re.I)
CODEHOST = re.compile(r'https?://(?:www\.)?(github\.com|gitlab\.com|codeberg\.org|bitbucket\.org)/', re.I)
TYPES = {  # type -> (BibTeX, RIS, CSL)
    'article': ('article', 'JOUR', 'article-journal'), 'preprint': ('misc', 'UNPB', 'article'), 'software': ('misc', 'COMP', 'software'),
    'dataset': ('misc', 'DATA', 'dataset'), 'legislation': ('misc', 'LEGAL', 'legislation'), 'case': ('misc', 'CASE', 'legal_case'),
    'trial': ('misc', 'GEN', 'document'), 'thesis': ('phdthesis', 'THES', 'thesis')}
BIBTEX_ESC = {'\\': r'\textbackslash{}', '{': r'\{', '}': r'\}', '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_',
              '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}


def _clean(s):
    return ' '.join(str(s or '').split()).strip(' ,;')


def _id(prefix, value):
    return f'{prefix.lower()}:{value.rstrip(".,;)]")}'


def bib_entries(report):
    """[(n, text)] of `## Bibliography` (a continuation line joins its entry, as in export_report)."""
    body = dict(sections(report)).get('Bibliography', ''); out = []
    for l in body.splitlines():
        if (m := BIB_LINE.match(l)): out.append([int(m.group(1)), m.group(2).strip()])
        elif l.strip() and out: out[-1][1] += ' ' + l.strip()
    return [tuple(e) for e in out]


def kind(ids, code, url, venue):
    p = {i.split(':', 1)[0] for i in ids}
    if code or 'osv' in p or (url and CODEHOST.match(url) and not p): return 'software'
    if 'nct' in p: return 'trial'
    if 'thesesfr' in p: return 'thesis'
    if 'ecli' in p or 'ja' in p: return 'case'
    if 'celex' in p: return 'case' if next(i for i in ids if i.startswith('celex:'))[6:7] == '6' else 'legislation'
    if 'zenodo' in p: return 'dataset'
    if ('arxiv' in p or 'hal' in p or 'openreview' in p) and not venue: return 'preprint'
    if p & {'doi', 'pmid', 'pmcid', 'arxiv', 'hal', 'openreview', 'dblp', 'econbiz'}: return 'article'
    return 'article' if venue else ''


def split_authors(s):
    """'Massé et al.' -> ['Massé'], etal True; names kept as written, an organisation stays one literal name."""
    s = _clean(s); etal = bool(ETAL.search(s)); s = ETAL.sub('', s).strip(' ,')
    parts = [p.strip(' ,') if re.search(r'\b[A-Z]\.$', p.strip()) else p.strip(' .,') for p in re.split(r';|,\s+|\s+and\s+|\s+&\s+', s)]
    return [p for p in parts if p], etal


def person(name):
    """-> {'family', 'given'} for a recognisable personal name, else {'literal'} (organisation, unusual form): never re-guessed."""
    if (m := PERSON[0].match(name)): return {'family': m.group(1), **({'given': m.group(2)} if m.group(2) else {})}
    if (m := PERSON[1].match(name)): return {'family': m.group(2), 'given': m.group(1).strip()}
    return {'literal': name}


def parse_text(text, known_titles):
    """Fields written in one bibliography line: authors, title, venue, year, identifiers, code ref, url, basis."""
    e = {'ids': [], 'code': None, 'url': '', 'basis': '', 'authors': '', 'title': '', 'venue': '', 'year': ''}
    for m in VPID.finditer(text):
        if (i := _id(m.group(1), m.group(2))) not in e['ids']: e['ids'].append(i)
    if (m := CODE.search(text)): e['code'] = {'path': m.group(1), 'line': m.group(2) or '', 'sha': m.group(3)}
    if (m := URL.search(text)): e['url'] = m.group(0).rstrip('.,;)')
    if (m := re.search(r'\bbasis:?\s*(abstract|title|full ?text)\s*\.?\s*$', text, re.I)): e['basis'] = m.group(1).lower()
    if e['code']:   # `owner/repo, `path:line@SHA` (...)`: the repo is the publisher, the path the title, the SHA the version
        e['venue'] = _clean(text[:text.find('`')]); e['title'] = e['code']['path']; return e
    stop = min([m.start() for m in (VPID.search(text), URL.search(text), re.search(r'\bbasis\b', text, re.I)) if m] + [len(text)])
    head = text[:stop]
    for t in known_titles:   # the title the annex gives, found in the line: authors before it, venue just after it
        for cand in (t, re.sub(r'\s*\([^()]*\)\s*$', '', t)):
            if cand and (i := head.lower().find(cand.lower())) >= 0:
                e['authors'] = head[:i].strip(' .,"“”'); e['title'] = head[i:i + len(cand)]; rest = head[i + len(cand):]
                if (m := re.match(r'\s*["”]?,\s*([^.]+?)\s*(?:[.,]|$)', rest)) and not YEAR.fullmatch(m.group(1).strip()): e['venue'] = _clean(m.group(1))
                if (y := YEAR.search(rest)): e['year'] = y.group(1)
                return e
    if (m := re.search(r'["“]([^"”]+)["”]', head)):   # quoted title
        e['authors'] = head[:m.start()].strip(' ,'); e['title'] = _clean(m.group(1)); rest = head[m.end():]
    else:   # Authors. Title. Year. : sentences split on ". " except after an initial
        segs = [s for s in re.split(r'(?<!\b[A-Z])\.\s+', head.strip()) if s.strip()]
        if len(segs) >= 2 and not YEAR.fullmatch(segs[1].strip(' .')): e['authors'], e['title'], rest = segs[0], _clean(segs[1].rstrip('.')), ' '.join(segs[2:])
        else: e['title'], rest = (_clean(segs[0].rstrip('.')) if segs and not YEAR.fullmatch(segs[0].strip(' .')) else ''), ' '.join(segs[1:])
    if (y := YEAR.search(rest)): e['year'] = y.group(1)
    return e


def _src_ids(src):
    return [_id(k, str(v)) for k, v in src.items() if k in IDS and k != 'code' and v] if isinstance(src, dict) else []


def entries(folder):
    """One dict per bibliography entry: n, type, authors [str], etal, title, year, venue, doi, url, vp_id, ids, basis, code, version."""
    d = pathlib.Path(folder); card, res = _json(d / 'card.json'), _json(d / 'result.json')
    srcs = card.get('sources') if isinstance(card, dict) and isinstance(card.get('sources'), dict) else {}
    studs = {str(s.get('id', '')).lower(): s for s in (res.get('studies') or []) if isinstance(s, dict)} if isinstance(res, dict) else {}
    out = []
    for n, text in bib_entries((d / 'REPORT.md').read_text(encoding='utf-8', errors='replace')):
        src = srcs.get(f'S{n}') if isinstance(srcs.get(f'S{n}'), dict) else {}
        pre = [m for m in (_id(m.group(1), m.group(2)) for m in VPID.finditer(text))]
        if src and pre and not set(_src_ids(src)) & set(pre) and not src.get('code'): src = {}   # S<n> is another document: ignored
        st = next((studs[i] for i in pre + _src_ids(src) if i in studs), {})
        e = parse_text(text, [t for t in (st.get('title'), src.get('title')) if isinstance(t, str) and t.strip()])
        ids = e['ids'] + [i for i in _src_ids(src) if i not in e['ids']]
        if st.get('id') and str(st['id']).lower() not in ids: ids.insert(0, str(st['id']).lower())
        code = e['code']
        if not code and isinstance(src.get('code'), str) and (m := re.match(r'(?:local:)?(.+)@([0-9a-f]{6,40})$', src['code'])): code = {'path': m.group(1), 'line': '', 'sha': m.group(2)}
        title = _clean(st.get('title') or src.get('title') or e['title'])
        if code and not e['title']: e['venue'], title = '', code['path']
        year = str(st.get('year') or e['year'] or '')
        vp = (str(st['id']).lower() if st.get('id') else ids[0] if ids else f"code:{code['path']}@{code['sha']}" if code else '')
        doi = next((i[4:] for i in ids if i.startswith('doi:')), '')
        url = e['url'] or next((IDLINK[p].format(v) for p, v in (i.split(':', 1) for i in ids) if p in IDLINK), '')
        authors, etal = split_authors(e['authors'])
        t = kind(ids, code, e['url'], e['venue'])
        out.append({'n': n, 'type': t, 'authors': authors, 'etal': etal, 'title': title, 'year': year if re.fullmatch(r'\d{4}', year) else '',
                    'venue': e['venue'], 'doi': doi, 'url': url, 'vp_id': vp, 'ids': ids, 'basis': e['basis'] or str(st.get('basis') or ''),
                    'code': code, 'version': code['sha'] if code else ''})
    return out


def note(e):
    return '; '.join(x for x in (f"VP id: {e['vp_id']}" if e['vp_id'] else '', f"other ids: {', '.join(i for i in e['ids'] if i != e['vp_id'])}"
                                 if len(e['ids']) > (e['vp_id'] in e['ids']) else '', f"basis: {e['basis']}" if e['basis'] else '', f"report [{e['n']}]") if x)


# ---------- BibTeX ----------
def tex(s):
    return ''.join(BIBTEX_ESC.get(c, c) for c in str(s))


def _verb(s):   # url / doi fields are read verbatim: only braces, backslash and spaces would break them
    return re.sub(r'[{}\\\s]', lambda m: '%%%02X' % ord(m.group(0)), str(s))


def keys(es):
    seen, out = {}, []
    for e in es:
        p = person(e['authors'][0]) if e['authors'] else {}
        a = p['family'].split()[-1] if p.get('family') else p['literal'].split()[0] if p else e['venue'].split('/')[-1] if e['code'] else ''
        w = next((x for x in re.findall(r'[A-Za-z0-9]+', _ascii(e['title'].split('/')[-1] if e['code'] else e['title'])) if len(x) > 3), '')
        base = re.sub(r'[^a-z0-9]', '', _ascii(a).lower()) + e['year'] + w.lower()
        base = base or f"ref{e['n']}"
        k = base if base not in seen else base + next(c for c in 'abcdefghijklmnopqrstuvwxyz' if base + c not in seen)
        seen[k] = 1; seen.setdefault(base, 1); out.append(k)
    return out


def _ascii(s):
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()


def bib_name(a):
    p = person(a)
    if 'literal' in p: return '{' + tex(a) + '}'
    return tex(p['family'] + (', ' + p['given'] if p.get('given') else ''))


def bibtex(es):
    out = []
    for k, e in zip(keys(es), es):
        bt = TYPES.get(e['type'], ('misc',))[0]; f = []
        if e['authors']: f.append(('author', ' and '.join(bib_name(a) for a in e['authors']) + (' and others' if e['etal'] else '')))
        if e['title']: f.append(('title', '{' + tex(e['title']) + '}'))
        if e['year']: f.append(('year', e['year']))
        if e['venue']: f.append(('journal' if bt == 'article' else 'school' if bt == 'phdthesis' else 'publisher' if e['code'] else 'howpublished', tex(e['venue'])))
        if e['version']: f.append(('version', e['version']))
        if e['doi']: f.append(('doi', _verb(e['doi'])))
        if (ax := next((i[6:] for i in e['ids'] if i.startswith('arxiv:')), '')): f += [('eprint', _verb(ax)), ('archiveprefix', 'arXiv')]
        if (pm := next((i[5:] for i in e['ids'] if i.startswith('pmid:')), '')): f.append(('pmid', _verb(pm)))
        if e['url']: f.append(('url', _verb(e['url'])))
        f.append(('note', tex(note(e))))
        out.append(f'@{bt}{{{k},\n' + ',\n'.join(f'  {n} = {{{v}}}' for n, v in f) + '\n}\n')
    return '\n'.join(out)


# ---------- RIS ----------
def ris(es):
    lines = []
    for e in es:
        r = TYPES.get(e['type'], (None, 'GEN'))[1]; one = lambda t, v: lines.append(f'{t}  - {_clean(v)}') if _clean(v) else None
        one('TY', r)
        for a in e['authors']: p = person(a); one('AU', a if 'literal' in p else p['family'] + (', ' + p['given'] if p.get('given') else ''))
        one('TI', e['title']); one('PY', e['year'])
        one('JO' if r == 'JOUR' else 'PB' if e['code'] else 'T2', e['venue']); one('ET', e['version'])
        one('DO', e['doi']); one('UR', e['url']); one('AN', e['vp_id']); one('N1', note(e))
        lines.append('ER  - '); lines.append('')
    return '\r\n'.join(lines)


# ---------- CSL-JSON ----------
def csl(es):
    out = []
    for k, e in zip(keys(es), es):
        c = {'id': k, 'type': TYPES.get(e['type'], (None, None, 'document'))[2], 'citation-label': f"[{e['n']}]"}
        if e['authors']: c['author'] = [person(a) for a in e['authors']]
        if e['title']: c['title'] = e['title']
        if e['year']: c['issued'] = {'date-parts': [[int(e['year'])]]}
        if e['venue']: c['publisher' if e['code'] else 'container-title'] = e['venue']
        if e['version']: c['version'] = e['version']
        if e['doi']: c['DOI'] = e['doi']
        for p, f in (('pmid', 'PMID'), ('pmcid', 'PMCID')):
            if (v := next((i.split(':', 1)[1] for i in e['ids'] if i.startswith(p + ':')), '')): c[f] = v
        if e['url']: c['URL'] = e['url']
        c['note'] = note(e); out.append(c)
    return json.dumps(out, ensure_ascii=False, indent=1) + '\n'


# ---------- studies.csv ----------
def _cell(v):
    if isinstance(v, bool) or v is None: v = '' if v is None else str(v).lower()
    if isinstance(v, (int, float)): return v
    if isinstance(v, (list, dict)): v = json.dumps(v, ensure_ascii=False)
    return "'" + v if v[:1] in ('=', '+', '-', '@', '\t', '\r') else v


def studies(folder, es=None):
    d = pathlib.Path(folder); res, card, ver = (_json(d / f) for f in ('result.json', 'card.json', 'verdicts.json'))
    st = [s for s in (res.get('studies') or []) if isinstance(s, dict)] if isinstance(res, dict) else []
    crit = [k for k in CRITERIA if any(isinstance(s.get('criteria'), dict) and k in s['criteria'] for s in st)]
    for s in st:
        for k in (s.get('criteria') or {}) if isinstance(s.get('criteria'), dict) else ():
            if k not in crit: crit.append(k)
    srcs = card.get('sources') if isinstance(card, dict) and isinstance(card.get('sources'), dict) else {}
    claims = [c for c in card.get('claims', []) if isinstance(c, dict)] if isinstance(card, dict) and isinstance(card.get('claims'), list) else []
    status = {str(v.get('id')): str(v.get('status')) for v in (ver.get('claims') or []) if isinstance(v, dict)} if isinstance(ver, dict) else {}
    es = entries(d) if es is None else es
    head = ['id', 'title', 'year'] + crit + ['confidence', 'basis', 'claims'] + [s.lower().replace('-', '_') for s in STATUSES] + ['no_verdict', 'ref']
    rows = []
    for s in st:
        sid = str(s.get('id', '')).lower()
        keys_ = {k for k, v in srcs.items() if sid and sid in _src_ids(v)}
        mine = [c for c in claims if isinstance(c.get('source'), dict) and c['source'].get('key') in keys_]
        cnt = {x: 0 for x in STATUSES}; nov = 0
        for c in mine:
            x = status.get(str(c.get('id')))
            if x in cnt: cnt[x] += 1
            else: nov += 1
        ref = next((e['n'] for e in es if sid and sid in e['ids']), '')
        cr = s.get('criteria') if isinstance(s.get('criteria'), dict) else {}
        rows.append([_cell(x) for x in [s.get('id', ''), s.get('title', ''), str(s.get('year', '') or '')] + [cr.get(k, '') for k in crit]
                     + [s.get('confidence', ''), s.get('basis', ''), len(mine)] + [cnt[x] for x in STATUSES] + [nov, ref]])
    return head, rows


def to_csv(head, rows):
    b = io.StringIO(); w = csv.writer(b, lineterminator='\r\n'); w.writerow(head); w.writerows(rows); return b.getvalue()


def main(argv=None):
    ap = argparse.ArgumentParser(description='Run dir -> studies.csv, references.bib / .ris / .json (CSL-JSON), offline.')
    ap.add_argument('run_dir'); ap.add_argument('--out'); a = ap.parse_args(argv)
    d = pathlib.Path(a.run_dir)
    if not (d / 'REPORT.md').is_file(): print(f'no REPORT.md in {d}', file=sys.stderr); return 2
    out = pathlib.Path(a.out) if a.out else d; out.mkdir(parents=True, exist_ok=True)
    es = entries(d); head, rows = studies(d, es)
    for name, text in (('studies.csv', to_csv(head, rows)), ('references.bib', bibtex(es)), ('references.ris', ris(es)), ('references.json', csl(es))):
        (out / name).write_bytes(text.encode('utf-8')); print((out / name).resolve())
    print(f'{len(rows)} studies, {len(es)} references')
    return 0


if __name__ == '__main__':
    sys.exit(main())
