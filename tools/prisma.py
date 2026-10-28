#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""PRISMA 2020 flow diagram of a run (optional, never by default). Standard library, offline, no model.
Built only from what the run recorded: the gateway journal (DIR/state/journal.jsonl, search pool only: the verifier's own pool is left out),
the searchers' files (DIR/searches/*.md: exclusion marks and their reasons, as the searchers wrote them), card.json (`sources`: reports of
the included studies), result.json (`studies`: included studies; `verification.entries_removed`). A box the data do not give is printed
"not recorded", never estimated.

How the run maps onto the PRISMA 2020 boxes (stated in the outputs too):
  identified, per source = records returned by each engine (search-<engine> and the code commands), plus citation searching (citing,
    references, related), plus "direct read" (identifiers read without having been returned by any call of the journal), plus the records the
    gateway's date barrier removed (dated on or after T, or forbidden: the journal's `excluded`);
  removed before screening = duplicates (same identifier returned more than once) and the date barrier;
  screened = distinct records left (a record without identifier counts once per occurrence: it cannot be deduplicated);
  reports sought for retrieval = distinct identifiers read (`read`) by the searchers; not retrieved = identifiers whose every read failed or
    was refused; assessed = sought - not retrieved; records excluded at screening = screened - sought;
  reports excluded = assessed and not cited in card.json, with the reasons the searchers wrote next to an "excluded" mark (else "reason not
    recorded"); included = card.json sources (reports) and result.json studies (studies); cited without a read (basis title, or the
    abstract served by the search) are counted apart.
Outputs: DIR/PRISMA.md (text/Markdown), DIR/PRISMA.svg (plain SVG, no script, no external resource), DIR/prisma.json (the numbers).
Usage: prisma.py RUN_DIR [--out DIR] [--json]     Exit: 0 written; 2 not a directory.
Import: build(dir) -> dict ; markdown(data) -> str ; svg(data) -> str ; journal(dir) -> [entries] ; norm_id(str) -> str ;
        search_summary(dir) -> dict (engines, queries, counts: also the denominator of tools/prior_art.py)."""
import argparse, html, json, pathlib, re, sys

P = pathlib.Path(__file__).resolve().parent
NR = 'not recorded'
CHAIN = ('citing', 'references', 'related')                  # citation searching (PRISMA "other methods")
SEARCH_POOL = (None, '', 'search')                           # journal entries of the searchers; any other pool (verifier) is left out


def _cfg():
    try: c = json.loads((P / 'config.json').read_text(encoding='utf-8')).get('prisma') or {}
    except (OSError, ValueError): c = {}
    svg = c.get('svg') or {}
    return {'reasons_max': int(c.get('reasons_max', 8)), 'reason_chars': int(c.get('reason_chars', 80)), 'mark_window': int(c.get('mark_window', 40)),
            'svg': {k: int(svg.get(k, v)) for k, v in (('box_w', 330), ('side_w', 300), ('line_h', 16), ('font_px', 12), ('pad', 10), ('gap', 26), ('chars_per_line', 46))}}


CFG = _cfg()
ID_PREFIXES = None


def _prefixes():
    """Identifier prefixes of the source registry (tools/sources/), longest first; fallback: the generic ones."""
    global ID_PREFIXES
    if ID_PREFIXES is None:
        try:
            sys.path.insert(0, str(P)); import sources as _reg
            ID_PREFIXES = sorted({i['field'] for i in _reg.IDS if i['field'] not in ('code', 'local')} | {i.get('prefix', i['field']) for i in _reg.IDS if i.get('prefix')} - {'code', 'local'}, key=len, reverse=True)
        except Exception:
            ID_PREFIXES = ['doi', 'pmid', 'pmcid', 'arxiv']
    return ID_PREFIXES


def norm_id(x):
    """'DOI:10.1/AB' -> 'doi:10.1/ab'; 'arxiv:2401.01234v2' -> 'arxiv:2401.01234'; URL forms of doi.org stripped. Empty -> ''."""
    s = str(x or '').strip().rstrip('.,;)')
    if not s: return ''
    s = re.sub(r'^https?://(dx\.)?doi\.org/', 'doi:', s, flags=re.I)
    if ':' not in s and re.match(r'^10\.\d{4,9}/', s): s = 'doi:' + s
    p, _, v = s.partition(':')
    p = p.lower()
    if p == 'doi': v = v.lower()
    if p == 'arxiv': v = re.sub(r'v\d+$', '', v)
    return f'{p}:{v}'


def card_ids(card):
    """card.json sources -> {key: set(normalised ids)} (code sources `path@SHA` kept as code:<value>)."""
    out = {}
    for k, s in ((card or {}).get('sources') or {}).items():
        if not isinstance(s, dict): continue
        ids = set()
        for f, v in s.items():
            if f in ('title', 'authors', 'year', 'note') or not isinstance(v, str) or not v.strip(): continue
            ids.add(norm_id(v if v.lower().startswith(f + ':') else f'{f}:{v}'))
        out[k] = ids
    return out


def _json(p):
    try: return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError): return None


def journal(d):
    """Search-pool entries of DIR/state/journal.jsonl (malformed lines skipped); [] when absent."""
    j = pathlib.Path(d) / 'state' / 'journal.jsonl'
    out = []
    if not j.is_file(): return out
    for l in j.read_text(encoding='utf-8', errors='replace').splitlines():
        try: e = json.loads(l)
        except ValueError: continue
        if isinstance(e, dict) and e.get('pool') in SEARCH_POOL: out.append(e)
    return out


def _kind(e):
    c = str(e.get('call') or '')
    if c == 'read': return 'read'
    if c in CHAIN: return 'chain'
    if c == 'sources': return 'none'
    return 'search'


def _source_name(e):
    c = str(e.get('call') or '')
    if _kind(e) == 'chain': return 'citation searching (citing/references/related)'
    return str(e.get('engine') or (c[7:] if c.startswith('search-') else c) or 'unknown')


def search_summary(d):
    """Engines, queries and counts of the searchers' calls (journal): the denominator of a 'not found'."""
    J = journal(d)
    per, queries, total = {}, [], {'calls': len(J), 'search_calls': 0, 'chain_calls': 0, 'read_calls': 0, 'errors': 0, 'records': 0, 'date_barrier': 0}
    seen = set()
    for e in J:
        k = _kind(e)
        if k == 'none': continue
        total['errors'] += bool(e.get('error'))
        if k == 'read': total['read_calls'] += 1; continue
        total['search_calls' if k == 'search' else 'chain_calls'] += 1
        ids = e.get('ids') or []
        name = _source_name(e)
        r = per.setdefault(name, {'calls': 0, 'records': 0, 'date_barrier': 0, 'errors': 0})
        r['calls'] += 1; r['records'] += len(ids); r['date_barrier'] += int(e.get('excluded') or 0); r['errors'] += bool(e.get('error'))
        total['records'] += len(ids); total['date_barrier'] += int(e.get('excluded') or 0)
        seen |= {norm_id(i) for i in ids if i}
        queries.append({'command': str(e.get('call')), 'engine': e.get('engine'), 'query': e.get('query'), 'records': len(ids),
                        'date_barrier': int(e.get('excluded') or 0), **({'error': str(e['error'])[:200]} if e.get('error') else {})})
    T = sorted({str(e.get('T')) for e in J if e.get('T')})
    return {'T': T, 'per_source': per, 'queries': queries, 'totals': {**total, 'distinct_ids': len(seen)}, 'journal': bool(J)}


# ---------------------------------------------------------------- exclusion marks of the searchers (searches/*.md)
EXCL = re.compile(r'\bexclud(?:ed|e|ing)\b', re.I)
NOT_A_MARK = re.compile(r'post-?T|gateway|barrier|after T|exclud\w*-leaning|\bno exclu|\bunless\b|\bnot exclud|exclud\w* to context|\(no excluded\)|none excluded', re.I)
HEADING = re.compile(r'^#{1,6}\s')


def _id_tokens(line, known):
    """Identifiers of a line: prefixed ones, then bare PMIDs / arXiv numbers following a `pmid:` / `arxiv:` list. Only ids the run
    recorded (journal) are kept, so years and figures are never taken for identifiers."""
    out = []
    for p in _prefixes():
        for m in re.finditer(r'(?<![\w/])' + re.escape(p) + r':\s?([^\s,;|()\[\]`"\']+)', line, re.I):
            out.append((m.start(), m.end(), norm_id(f'{p}:{m.group(1)}')))
    for p, rx in (('pmid', r'(?<![\w.:/-])(\d{5,9})(?![\w.])'), ('arxiv', r'(?<![\w.:/-])(\d{4}\.\d{4,5})(?:v\d+)?(?![\w])')):
        if f'{p}:' in line.lower():
            for m in re.finditer(rx, line):
                i = norm_id(f'{p}:{m.group(1)}')
                if not any(a <= m.start() < b for a, b, _ in out): out.append((m.start(), m.end(), i))
    out.sort()
    return [(a, b, i) for a, b, i in out if i in known]


def _clean_reason(s):
    s = re.sub(r'[*_`]+', '', str(s or '')).strip(' :;,.-—–()|')
    s = re.sub(r'\s+', ' ', s)
    if len(s) > CFG['reason_chars']: s = s[:CFG['reason_chars']].rsplit(' ', 1)[0] + '...'
    return s


def _reason_after_mark(line):
    m = EXCL.search(line)
    if not m: return ''
    rest = line[m.end():]
    if re.match(r'\s*\(', rest):
        k = rest.index('('); depth, j = 0, k
        for j in range(k, len(rest)):
            depth += rest[j] == '('; depth -= rest[j] == ')'
            if depth == 0: break
        return _clean_reason(rest[k + 1:j])
    rest = re.sub(r'^\s*(?:[:\-—–/]|as\b|because\b|for\b)?\s*', '', rest)
    return _clean_reason(re.split(r'[.;|\n]', rest, 1)[0])


def _is_mark(text):
    m = EXCL.search(text or '')
    return bool(m) and not NOT_A_MARK.search(text[max(0, m.start() - CFG['mark_window']):m.end() + CFG['mark_window']])


def _mark(line, exclude_spans=()):
    """First exclusion mark of the line outside the identifiers' own parentheses, unless its neighbourhood says it is not a decision."""
    for m in EXCL.finditer(line):
        if any(a <= m.start() < b for a, b in exclude_spans): continue
        if NOT_A_MARK.search(line[max(0, m.start() - CFG['mark_window']):m.end() + CFG['mark_window']]): continue
        return m
    return None


VAGUE = re.compile(r'^(with reasons?|above|below|see above|see below|\?)?$', re.I)


def _put(out, i, r):
    """First recorded reason wins; an empty or vague one ("above", "with reason") is replaced by a later informative one."""
    r = '' if VAGUE.match(r or '') else r
    if not out.get(i): out[i] = r or out.get(i, '')


def exclusion_marks(d, known):
    """searches/*.md -> {id: reason or ''}: identifiers on a line, or under a heading / label, that marks them excluded."""
    out = {}
    for p in sorted((pathlib.Path(d) / 'searches').glob('*.md')) if (pathlib.Path(d) / 'searches').is_dir() else []:
        block_reason = None
        for line in p.read_text(encoding='utf-8', errors='replace').splitlines():
            if HEADING.match(line) or not line.strip():
                block_reason = None
                if HEADING.match(line) and _is_mark(line): block_reason = _reason_after_mark(line) or ''
                continue
            if re.match(r'^\s*[^:]{0,60}?\bexclud\w*\b[^:]*:\s*$', line, re.I) and _is_mark(line):   # "EXCLUDED (with reason):" label
                block_reason = _reason_after_mark(line.rstrip(': ')) or ''; continue
            toks = _id_tokens(line, known)
            if not toks: continue
            own = {}
            for a, b, i in toks:
                mo = re.match(r'\s*\(([^)]{2,300})\)', line[b:])
                if mo: own[i] = mo.group(1)
            inside = [i for a, b, i in toks if i in own and _is_mark(own[i])]
            m = _mark(line, exclude_spans=[(b, b + 2 + len(own[i])) for a, b, i in toks if i in own])
            if inside:
                for i in inside: _put(out, i, _clean_reason(EXCL.sub('', own[i])))
            elif m:
                label_first = m.start() < toks[0][0]
                label = re.split(r'[:]', line[m.end():toks[0][0]], 1)[0] if label_first else ''
                for a, b, i in toks:
                    if label_first and a < m.start(): continue
                    r = _clean_reason(own[i]) if label_first and i in own else (_clean_reason(label.lstrip('/ ')) if label_first and label.strip(' /:') else _reason_after_mark(line[m.start():]))
                    _put(out, i, r)
            elif block_reason is not None:
                tail = _clean_reason(re.split(r'\s[-—–|]\s', line)[-1]) if len(re.split(r'\s[-—–|]\s', line)) > 1 else ''
                for a, b, i in toks: _put(out, i, ('' if VAGUE.match(block_reason) else block_reason) or tail)
    return out


# ---------------------------------------------------------------- the numbers
def build(d):
    d = pathlib.Path(d)
    J = journal(d)
    card = _json(d / 'card.json'); res = _json(d / 'result.json')
    card = card if isinstance(card, dict) else None; res = res if isinstance(res, dict) else None
    data = {'dir': str(d), 'T': sorted({str(e.get('T')) for e in J if e.get('T')}), 'journal': bool(J)}
    if not J:
        data['identification'] = data['screening'] = None
    else:
        per, occ, none_id, barrier = {}, [], 0, 0
        returned = set()
        for e in J:
            k = _kind(e)
            if k in ('read', 'none'): continue
            ids = e.get('ids') or []
            name = _source_name(e)
            r = per.setdefault(name, {'records': 0, 'date_barrier': 0, 'calls': 0})
            r['calls'] += 1; r['records'] += len(ids) + int(e.get('excluded') or 0); r['date_barrier'] += int(e.get('excluded') or 0)
            barrier += int(e.get('excluded') or 0)
            for i in ids:
                if i: occ.append(norm_id(i)); returned.add(norm_id(i))
                else: none_id += 1
        reads = {}
        for e in J:
            if _kind(e) != 'read': continue
            i = norm_id(e.get('query'))
            if not i: continue
            ok = not e.get('error') and any(x for x in (e.get('ids') or []))
            reads[i] = reads.get(i, False) or ok
        direct = sorted(set(reads) - returned)
        if direct: per['direct read (identifier not returned by a search)'] = {'records': len(direct), 'date_barrier': 0, 'calls': len(direct)}
        distinct = set(occ) | set(direct)
        identified = sum(r['records'] for r in per.values())
        duplicates = len(occ) - len(set(occ))
        screened = len(distinct) + none_id
        sought = set(reads)
        not_retrieved = {i for i, ok in reads.items() if not ok}
        assessed = sought - not_retrieved
        data['identification'] = {'per_source': per, 'identified': identified, 'records_without_identifier': none_id,
                                  'removed_before_screening': {'duplicates': duplicates, 'date_barrier': barrier, 'automation': NR}}
        data['screening'] = {'screened': screened, 'excluded_at_screening': screened - len(sought), 'sought': len(sought),
                             'not_retrieved': len(not_retrieved), 'not_retrieved_ids': sorted(not_retrieved), 'assessed': len(assessed)}
    # included
    cids = card_ids(card) if card else {}
    inc_ids = set().union(*cids.values()) if cids else set()
    studies = res.get('studies') if res and isinstance(res.get('studies'), list) else None
    removed = (res.get('verification') or {}).get('entries_removed') if res and isinstance(res.get('verification'), dict) else None
    data['included'] = {'reports': len(cids) if card else NR, 'studies': len(studies) if studies is not None else NR,
                        'entries_removed_after_verification': removed if isinstance(removed, int) else NR}
    if data['screening'] is not None:
        sc = data['screening']
        assessed = {i for i in _assessed_ids(J)}
        cited_keys_assessed = [k for k, ids in cids.items() if ids & assessed]
        sc['included_from_assessed'] = len(cited_keys_assessed) if card else NR
        sc['included_without_read'] = (len(cids) - len(cited_keys_assessed)) if card else NR
        if card:
            excl_ids = assessed - inc_ids
            marks = exclusion_marks(d, set(_known_ids(J)))
            reasons = {}
            for i in sorted(excl_ids):
                r = marks.get(i)
                reasons.setdefault(r if r else 'reason not recorded', []).append(i)
            sc['reports_excluded'] = len(excl_ids)
            sc['reasons'] = [{'reason': r, 'n': len(v), 'ids': v} for r, v in sorted(reasons.items(), key=lambda x: (x[0] == 'reason not recorded', -len(x[1]), x[0]))]
        else:
            sc['reports_excluded'] = NR; sc['reasons'] = []
    return data


def _assessed_ids(J):
    reads = {}
    for e in J:
        if _kind(e) != 'read': continue
        i = norm_id(e.get('query'))
        if i: reads[i] = reads.get(i, False) or (not e.get('error') and any(x for x in (e.get('ids') or [])))
    return [i for i, ok in reads.items() if ok]


def _known_ids(J):
    for e in J:
        for i in e.get('ids') or []:
            if i: yield norm_id(i)
        if _kind(e) == 'read' and e.get('query'): yield norm_id(e.get('query'))


def _n(x): return NR if x is None else str(x)


DEFINITIONS = ('Derived by tools/prisma.py from the gateway journal (searchers only), searches/*.md, card.json and result.json; '
               '"not recorded" = the run did not record it. Screened = distinct records after deduplication; reports sought = identifiers read '
               'by the searchers; included = card.json sources (reports) and result.json studies; exclusion reasons as written by the searchers.')


def boxes(data):
    """The PRISMA 2020 boxes as (stage, main lines, side lines) from build()."""
    idf, sc, inc = data.get('identification'), data.get('screening'), data['included']
    out = []
    if idf is None:
        out.append(('Identification', ['Records identified: ' + NR + ' (no state/journal.jsonl)'], ['Records removed before screening: ' + NR]))
        out.append(('Screening', ['Records screened: ' + NR], ['Records excluded: ' + NR]))
        out.append(('Screening', ['Reports sought for retrieval: ' + NR], ['Reports not retrieved: ' + NR]))
        out.append(('Screening', ['Reports assessed for eligibility: ' + NR], ['Reports excluded: ' + NR]))
    else:
        main = [f'Records identified (n = {idf["identified"]}):'] + [f'  {k}: n = {v["records"]}' for k, v in sorted(idf['per_source'].items(), key=lambda x: -x[1]['records'])]
        rb = idf['removed_before_screening']
        side = ['Records removed before screening:', f'  duplicate records: n = {rb["duplicates"]}', f'  dated on/after T or forbidden (gateway barrier): n = {rb["date_barrier"]}',
                f'  marked ineligible by automation tools: {rb["automation"]}']
        if idf['records_without_identifier']: side.append(f'  (records without identifier, not deduplicable: {idf["records_without_identifier"]})')
        out.append(('Identification', main, side))
        out.append(('Screening', [f'Records screened (n = {sc["screened"]})'], [f'Records excluded at screening (n = {sc["excluded_at_screening"]})']))
        out.append(('Screening', [f'Reports sought for retrieval (n = {sc["sought"]})'], [f'Reports not retrieved (n = {sc["not_retrieved"]})']))
        rex = sc.get('reports_excluded')
        side = [f'Reports excluded (n = {_n(rex)}):' if rex != NR else f'Reports excluded: {NR}']
        rs = sc.get('reasons') or []
        for r in rs[:CFG['reasons_max']]: side.append(f'  {r["reason"]}: n = {r["n"]}')
        if len(rs) > CFG['reasons_max']: side.append(f'  other recorded reasons: n = {sum(r["n"] for r in rs[CFG["reasons_max"]:])}')
        out.append(('Screening', [f'Reports assessed for eligibility (n = {sc["assessed"]})'], side))
    main = [f'Studies included in review (n = {_n(inc["studies"])})' if inc['studies'] != NR else f'Studies included in review: {NR}',
            f'Reports of included studies (n = {_n(inc["reports"])})' if inc['reports'] != NR else f'Reports of included studies: {NR}']
    side = []
    if sc is not None and sc.get('included_without_read') not in (None, NR):
        side.append(f'Of the reports: read and assessed n = {sc["included_from_assessed"]}; cited without a read (title or search abstract) n = {sc["included_without_read"]}')
    if inc['entries_removed_after_verification'] != NR: side.append(f'Entries removed after verification: n = {inc["entries_removed_after_verification"]}')
    out.append(('Included', main, side))
    return out


def markdown(data):
    L = ['# PRISMA 2020 flow diagram', '', f'Run: `{pathlib.Path(data["dir"]).name}`' + (f'; date T: {", ".join(data["T"])}' if data.get('T') else ''), '']
    stage = None
    for st, main, side in boxes(data):
        if st != stage: L += [f'## {st}', '']; stage = st
        L += [f'- {x}' if not x.startswith('  ') else f'  - {x.strip()}' for x in main]
        L += [f'  - -> {x}' if not x.startswith('  ') else f'    - {x.strip()}' for x in side]
        L.append('')
    sc = data.get('screening') or {}
    if sc.get('not_retrieved_ids'): L += ['Not retrieved: ' + ', '.join(f'`{i}`' for i in sc['not_retrieved_ids']), '']
    L += ['## How the numbers were derived', '', DEFINITIONS, '']
    return '\n'.join(L)


def _wrap(s, width):
    words, out, cur = s.split(' '), [], ''
    lead = len(s) - len(s.lstrip(' '))
    for w in [x for x in words if x]:
        if cur and len(cur) + 1 + len(w) > width: out.append(cur); cur = ' ' * (lead + 2) + w
        else: cur = (cur + ' ' + w) if cur else ' ' * lead + w
    if cur: out.append(cur)
    return out or ['']


def svg(data):
    """Plain SVG: stage labels on the left, the main boxes in a column joined by arrows, the side boxes to the right. Text escaped."""
    c = CFG['svg']; lh, pad, gap, fpx = c['line_h'], c['pad'], c['gap'], c['font_px']
    label_w = lh * 2; x_main = label_w + pad; x_side = x_main + c['box_w'] + gap
    W = x_side + c['side_w'] + pad
    y = pad + lh * 2
    els = [f'<text x="{pad}" y="{pad + lh}" font-size="{fpx + 2}" font-weight="bold">PRISMA 2020 flow diagram</text>']
    prev_bottom, stage_spans = None, []
    for st, main, side in boxes(data):
        ml = [l for x in main for l in _wrap(x, c['chars_per_line'])]
        sl = [l for x in side for l in _wrap(x, c['chars_per_line'] * c['side_w'] // c['box_w'])]
        h = max(len(ml), len(sl)) * lh + pad * 2
        if prev_bottom is not None:
            els.append(f'<line x1="{x_main + c["box_w"] // 2}" y1="{prev_bottom}" x2="{x_main + c["box_w"] // 2}" y2="{y - 2}" stroke="#333" marker-end="url(#a)"/>')
        els.append(f'<rect x="{x_main}" y="{y}" width="{c["box_w"]}" height="{h}" fill="#fff" stroke="#333"/>')
        for k, l in enumerate(ml):
            els.append(f'<text x="{x_main + pad}" y="{y + pad + (k + 1) * lh - 4}" font-size="{fpx}" xml:space="preserve">{html.escape(l)}</text>')
        if sl:
            els.append(f'<line x1="{x_main + c["box_w"]}" y1="{y + h // 2}" x2="{x_side - 2}" y2="{y + h // 2}" stroke="#333" marker-end="url(#a)"/>')
            els.append(f'<rect x="{x_side}" y="{y}" width="{c["side_w"]}" height="{h}" fill="#f6f6f8" stroke="#333"/>')
            for k, l in enumerate(sl):
                els.append(f'<text x="{x_side + pad}" y="{y + pad + (k + 1) * lh - 4}" font-size="{fpx}" xml:space="preserve">{html.escape(l)}</text>')
        if stage_spans and stage_spans[-1][0] == st: stage_spans[-1][2] = y + h
        else: stage_spans.append([st, y, y + h])
        prev_bottom = y + h; y += h + gap
    for st, a, b in stage_spans:
        els.append(f'<rect x="{pad // 2}" y="{a}" width="{label_w - pad // 2}" height="{b - a}" fill="#dfe8f5" stroke="#333"/>')
        cx, cy = pad // 2 + (label_w - pad // 2) // 2, (a + b) // 2
        els.append(f'<text x="{cx}" y="{cy}" font-size="{fpx}" font-weight="bold" text-anchor="middle" transform="rotate(-90 {cx} {cy})">{html.escape(st)}</text>')
    H = y + pad
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Arial, Helvetica, sans-serif" role="img" '
            f'aria-label="PRISMA 2020 flow diagram">\n<defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
            f'<path d="M0,0 L8,4 L0,8 z" fill="#333"/></marker></defs>\n<rect width="{W}" height="{H}" fill="#fff"/>\n' + '\n'.join(els) + '\n</svg>\n')


def write(d, out=None):
    d = pathlib.Path(d); o = pathlib.Path(out) if out else d; o.mkdir(parents=True, exist_ok=True)
    data = build(d)
    (o / 'PRISMA.md').write_text(markdown(data), encoding='utf-8')
    (o / 'PRISMA.svg').write_text(svg(data), encoding='utf-8')
    (o / 'prisma.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    return data, [o / 'PRISMA.md', o / 'PRISMA.svg', o / 'prisma.json']


def main(argv=None):
    ap = argparse.ArgumentParser(description='PRISMA 2020 flow diagram of a run (text/Markdown + SVG), from its own records. Offline, no model.')
    ap.add_argument('run_dir'); ap.add_argument('--out'); ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    if not pathlib.Path(a.run_dir).is_dir(): print(f'not a directory: {a.run_dir}', file=sys.stderr); return 2
    data, files = write(a.run_dir, a.out)
    if a.json: print(json.dumps(data, ensure_ascii=False, indent=1))
    for f in files: print(f.resolve())
    return 0


if __name__ == '__main__':
    sys.exit(main())
