#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Evidence bank of a run: the optional quote-first writing mode (SKILL.md "Quote-first writing (optional, never by default)").
Standard library, offline, no model call, no gateway call.

Before writing, the orchestrator extracts verbatim quotes from the sources it read into DIR/evidence.json:
  {"origin": "orchestrator", "evidence": [{"id": "E1", "source": "S1" | "<identifier>", "quote": "...",
                                           "sections": ["Finding 1", ...], "claims": ["A1", ...]}]}
`sections` (optional) = the report sections allowed to use the item (a level-2 title, or the start of a level-3 title such as
"Finding 2"); `claims` (optional) = the card claims it supports. Each section is then written from its own items only.

Checks on the bank (code only):
  EB1 format: an object with an `evidence` list; each item has an id E<n> (unique), a `source` and a `quote` string, and optional
      `sections` / `claims` lists of strings;
  EB2 source known: a key of card.json `sources`, an identifier one of them carries, or an identifier named in DIR/state/journal.jsonl;
  EB3 quote length: at least citation_check.MIN_CHARS non-blank characters, at most evidence_bank.max_quote_chars characters;
  EB4 quote served: an exact substring (NFKC, whitespace ignored, the rule of tools/verifier/citation_check.py) of a text the run kept
      from the gateway: DIR/sources/<KEY>/source.txt, DIR/state/fulltext/*/source.txt, or an answer of the gateway cache
      DIR/state/cache/* (JSON string values, or the text, each also with HTML/XML entities decoded and tags removed; binary answers and
      answers over evidence_bank.cache_max_bytes are not read). A quote found nowhere is `not_served`;
  EB5 quote attributed: found in a text of the source itself: its sources/<KEY>/source.txt, its state/fulltext/<identifier>/source.txt,
      or, in a gateway cache answer, the record of that identifier only: a JSON object (or XML element) one of whose own short fields
      (at most evidence_bank.record_id_max_chars characters) names the identifier, with everything under it; an answer that is neither
      JSON nor XML counts only when it names this identifier and no other identifier of the run (card and journal). A list of results
      that merely cites the identifier never lends another record's text to it. A quote served only under another source is
      `misattributed`;
  W1 (warning only): no identifier of the source appears in DIR/state/journal.jsonl.
Tie to the report: each sentence of REPORT.md that carries a [n] (outside evidence_bank.skip_sections) goes [n] -> card key
(tools/passages.refs_of) -> valid items of that source allowed in the sentence's section; every such item sharing a content term or a
figure with the sentence is linked. The sentence is
  supported        the linked items share at least evidence_bank.min_shared_terms content terms with it, and every figure of the
                   sentence (years excluded when evidence_bank.ignore_years) appears in a linked quote;
  partial          an item of a cited source is linked, but terms or figures are missing (the missing figures are listed);
  outside_section  its cited sources have valid items, all attributed to other sections;
  no_evidence      no valid item for any of its cited sources;
  unmapped         none of its [n] resolves to a card source.
Measure: supported_share = supported / sentences carrying a [n]. It measures traceability to an extracted quote, not truth: the
meaning is still judged by the verifier (SKILL.md section 7). Terms: text_terms of tools/config.json.

Usage:
  evidence_bank.py DIR [--bank FILE] [--out DIR] [--json] [--html]   check the bank, tie the report, write EVIDENCE.md and
                                                                       evidence_check.json (and EVIDENCE.html with --html)
  evidence_bank.py DIR --section "Finding 2" [--bank FILE]            print the valid items that section may use (inert Markdown)
  evidence_bank.py DIR --from-verdicts [--bank FILE] [--out DIR]      write an APPROXIMATE bank from the verifier's fragments (FOUND and
                                                                       DISTORTED), origin "verifier-fragments", then check it; written to
                                                                       --bank, else --out/evidence.json, else DIR/evidence.json, and never
                                                                       over an existing file (refused, exit 2)
Exit: 0 bank valid; 1 invalid items (listed); 2 not a directory, or no bank.
Import: served_texts(dir), check_bank(dir, bank), report_units(md), tie_report(dir, checked), build(dir, bank=None) -> dict,
markdown(doc), html_page(doc), terms(text), numbers(text)."""
import argparse, hashlib, html, json, pathlib, re, sys, unicodedata

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE / 'verifier'))
from citation_check import MIN_CHARS, norm                  # noqa: E402  (same normalisation and minimum as the fragment check)
import passages as PS                                       # noqa: E402  (refs_of, fs_key, _code, _fence)
from export_report import CITE_RE                           # noqa: E402  (the [n] / [n, m] citation syntax of the report)
import report_lang as RL                                     # noqa: E402  (canonical titles of the sections, any language)


def _config():
    try: c = json.loads((HERE / 'config.json').read_text(encoding='utf-8'))
    except (OSError, ValueError): c = {}
    t, e = c.get('text_terms') or {}, c.get('evidence_bank') or {}
    return {'stopwords': {w.casefold() for w in (t.get('stopwords') or [])}, 'min_term_chars': int(t.get('min_term_chars', 3)),
            'max_quote_chars': int(e.get('max_quote_chars', 1200)), 'min_shared_terms': int(e.get('min_shared_terms', 2)),
            'ignore_years': bool(e.get('ignore_years', True)), 'skip_sections': list(e.get('skip_sections') or ['Bibliography', 'Methodology Appendix']),
            'cache_max_bytes': int(e.get('cache_max_bytes', 20000000)), 'shown_chars': int(e.get('shown_chars', 400)),
            'record_id_max_chars': int(e.get('record_id_max_chars', 300))}


CFG = _config()
WORD = re.compile(r"[^\W\d_][\w'’-]*")
NUM = re.compile(r'(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+)(?:[.,](\d+))?(?![\d])')
TAG = re.compile(r'<[^<>]{0,400}>')
EID = re.compile(r'^E\d{1,5}$')
STATUSES = ('valid', 'invalid')


# ---------- text helpers (shared with tools/contradictions.py) ----------
def stem(w):
    w = w.casefold().strip("'’-")
    if w.endswith(("'s", "’s")): w = w[:-2]
    if len(w) > 4 and w.endswith('ies'): return w[:-3] + 'y'
    if len(w) > 3 and w.endswith('s') and not w.endswith(('ss', 'us', 'is')): return w[:-1]
    return w


def terms(text, cfg=None):
    """Content terms of a text: words (citations [n] removed) of at least text_terms.min_term_chars letters, not stopwords, stemmed."""
    cfg = cfg or CFG
    out = set()
    for w in WORD.findall(CITE_RE.sub(' ', unicodedata.normalize('NFKC', str(text or '')))):
        for part in re.split(r'[-’\']', w):
            s = stem(part)
            if len(s) >= cfg['min_term_chars'] and s not in cfg['stopwords']: out.add(s)
    return out


def numbers(text, ignore_years=None):
    """Figures of a text as floats (citations [n] removed; '1,000' = 1000, '62,8' = 62.8); years 1800-2100 dropped when ignore_years."""
    iy = CFG['ignore_years'] if ignore_years is None else ignore_years
    out = []
    for m in NUM.finditer(CITE_RE.sub(' ', unicodedata.normalize('NFKC', str(text or '')))):
        whole = m.group(1).replace(',', '')
        v = float(whole + ('.' + m.group(2) if m.group(2) else ''))
        if iy and not m.group(2) and 1800 <= v <= 2100 and len(whole) == 4: continue
        out.append(round(v, 6))
    return out


def _json(p):
    try: return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError): return None


def _strings(o, out):
    if isinstance(o, str): out.append(o)
    elif isinstance(o, dict):
        for v in o.values(): _strings(v, out)
    elif isinstance(o, list):
        for v in o: _strings(v, out)
    return out


def _text_views(base):
    """Normalised views of a text: as is, and entity-decoded and tag-stripped."""
    return [v for v in {norm(base), norm(TAG.sub(' ', html.unescape(base)))} if v]


def _views(raw):
    """Normalised texts of one gateway answer (bytes): JSON string values, or the text; each also entity-decoded and tag-stripped."""
    if raw[:5] == b'%PDF-' or b'\x00' in raw[:2048]: return []
    t = raw.decode('utf-8', errors='replace')
    try: base = '\n'.join(_strings(json.loads(t), []))
    except ValueError: base = t
    return _text_views(base)


def _id_field(v):
    return isinstance(v, (str, int, float)) and not isinstance(v, bool) and 0 < len(str(v)) <= CFG['record_id_max_chars']


def _json_records(o, out):
    """Records of a JSON answer: every object with its own short scalar fields (where an identifier is named) and its strings (lazy)."""
    if isinstance(o, dict):
        own = [str(v) for v in o.values() if _id_field(v)]
        if own: out.append({'names': html.unescape(' '.join(own)).casefold(), 'text': (lambda o=o: '\n'.join(_strings(o, [])))})
        for v in o.values(): _json_records(v, out)
    elif isinstance(o, list):
        for v in o: _json_records(v, out)
    return out


def _xml_records(t):
    """Records of an XML answer: every element with its own short leaf texts and attributes, and all the text under it; None: not XML."""
    import xml.etree.ElementTree as ET
    try: root = ET.fromstring(t)
    except (ET.ParseError, ValueError): return None
    out = []
    for el in root.iter():
        own = [c.text.strip() for c in el if len(c) == 0 and c.text and _id_field(c.text.strip())] + [v for v in el.attrib.values() if _id_field(v)]
        if own: out.append({'names': html.unescape(' '.join(own)).casefold(), 'text': (lambda el=el: ' '.join(el.itertext()))})
    return out


def _records(raw):
    """Per-identifier records of one cache answer; None when the answer is neither JSON nor XML (opaque: judged as a whole)."""
    t = raw.decode('utf-8', errors='replace')
    try: return _json_records(json.loads(t), [])
    except ValueError: return _xml_records(t.encode('utf-8'))


def served_texts(folder):
    """Texts the run kept from the gateway: [{'where', 'kind', 'name', 'texts': [normalised], 'raw_lower'}]."""
    d = pathlib.Path(folder); out = []
    for f in sorted((d / 'sources').glob('*/source.txt')):
        t = f.read_text(encoding='utf-8', errors='replace')
        out.append({'where': f'sources/{f.parent.name}/source.txt', 'kind': 'source', 'name': f.parent.name, 'texts': [norm(t)], 'raw_lower': ''})
    for f in sorted((d / 'state' / 'fulltext').glob('*/source.txt')):
        t = f.read_text(encoding='utf-8', errors='replace')
        out.append({'where': f'state/fulltext/{f.parent.name}/source.txt', 'kind': 'fulltext', 'name': f.parent.name, 'texts': [norm(t)], 'raw_lower': ''})
    cache = d / 'state' / 'cache'
    if cache.is_dir():
        for f in sorted(cache.iterdir()):
            try:
                if not f.is_file() or f.stat().st_size > CFG['cache_max_bytes']: continue
                raw = f.read_bytes()
            except OSError: continue
            v = _views(raw)
            if v: out.append({'where': f'state/cache/{f.name[:16]}', 'kind': 'cache', 'name': f.name, 'texts': v,
                              'raw_lower': html.unescape(raw.decode('utf-8', errors='replace')).casefold(), 'path': f})
    return out


def run_ids(card, journal_path):
    """Every identifier the run knows (card sources, `ids` of the journal lines), lower-cased."""
    ids = set()
    for desc in (card.get('sources') or {}).values() if isinstance(card.get('sources'), dict) else []: ids |= set(card_ids(desc))
    try: lines = pathlib.Path(journal_path).read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError: lines = []
    for ln in lines:
        try: j = json.loads(ln)
        except ValueError: continue
        if isinstance(j, dict): ids |= {str(i).casefold() for i in j.get('ids') or [] if isinstance(i, (str, int))}
    return ids


def own_cache_hit(t, ids, nq, known):
    """Is the normalised quote nq in the record of one of these identifiers inside this cache answer (EB5)?"""
    if not any(_names(t['raw_lower'], i) for i in ids): return False
    if 'records' not in t:                                 # parsed only for the answers that name the identifier, once per check
        try: t['records'] = _records(pathlib.Path(t['path']).read_bytes()) if t.get('path') else None
        except OSError: t['records'] = None
    recs = t['records']
    if recs is None:                                       # neither JSON nor XML: the whole answer, only if it names no other identifier
        mine = {_id_value(i).casefold() for i in ids}
        if any(_names(t['raw_lower'], o) for o in known if _id_value(o).casefold() not in mine): return False
        return any(nq in v for v in t['texts'])
    return any(nq in v for r in recs if any(_names(r['names'], i) for i in ids) for v in _text_views(r['text']()))


def journal_text(folder):
    try: return (pathlib.Path(folder) / 'state' / 'journal.jsonl').read_text(encoding='utf-8', errors='replace').casefold()
    except OSError: return ''


def card_ids(desc):
    """VP identifiers carried by a card source ('pmid:123', 'doi:10....'), lower-cased."""
    try:
        import export_data as X
        return [i.casefold() for i in X._src_ids(desc)]
    except Exception:
        return []


def _id_value(ident):
    return ident.split(':', 1)[1] if ':' in ident else ident


def _names(text, ident):
    """Does a lower-cased text name this identifier (its value, bounded so that pmid 123 is not found inside 91234)?"""
    v = _id_value(ident).casefold()
    if len(v) < 4: return False
    return re.search(r'(?<![\w.])' + re.escape(v) + r'(?![\w])', text) is not None


# ---------- bank ----------
def resolve_source(src, card, journal):
    """Item source -> (card key or None, [identifiers]) ; (None, []) when unknown."""
    table = card.get('sources') if isinstance(card.get('sources'), dict) else {}
    if src in table: return src, card_ids(table[src])
    s = str(src).strip().casefold()
    for k, desc in table.items():
        if s in card_ids(desc): return k, card_ids(desc)
    if re.match(r'^[a-z]+:\S+$', s) and s in journal: return None, [s]
    return None, []


def check_bank(folder, bank, texts=None):
    """bank (parsed JSON) -> {'items': [...], 'problems': [...], 'warnings': [...]}; each item gets status valid / invalid."""
    d = pathlib.Path(folder)
    card = _json(d / 'card.json'); card = card if isinstance(card, dict) else {}
    journal = journal_text(d)
    known = run_ids(card, d / 'state' / 'journal.jsonl')
    texts = served_texts(d) if texts is None else texts
    problems, warnings, items, seen = [], [], [], set()
    if not isinstance(bank, dict) or not isinstance(bank.get('evidence'), list):
        return {'items': [], 'problems': [{'check': 'EB1', 'id': None, 'why': 'the bank is not an object with an "evidence" list'}], 'warnings': []}
    for k, it in enumerate(bank['evidence']):
        why = []
        if not isinstance(it, dict):
            problems.append({'check': 'EB1', 'id': f'#{k + 1}', 'why': 'item is not an object'}); continue
        iid = it.get('id')
        if not isinstance(iid, str) or not EID.match(iid): why.append(('EB1', 'id must be E<n>'))
        elif iid in seen: why.append(('EB1', 'duplicate id'))
        seen.add(iid if isinstance(iid, str) else None)
        quote, src = it.get('quote'), it.get('source')
        if not isinstance(quote, str) or not isinstance(src, str): why.append(('EB1', 'source and quote must be strings'))
        for f in ('sections', 'claims'):
            if f in it and not (isinstance(it[f], list) and all(isinstance(x, str) for x in it[f])): why.append(('EB1', f'{f} must be a list of strings'))
        rec = {'id': iid if isinstance(iid, str) and EID.match(iid) else f'#{k + 1}', 'source': src if isinstance(src, str) else '', 'quote': quote if isinstance(quote, str) else '',
               'sections': [x for x in it.get('sections') or [] if isinstance(x, str)], 'claims': [x for x in it.get('claims') or [] if isinstance(x, str)],
               'key': None, 'served': None, 'where': None}
        if not why:
            key, ids = resolve_source(src, card, journal)
            rec['key'] = key; rec['ids'] = ids
            if key is None and not ids: why.append(('EB2', 'source unknown: not a card key, not a card identifier, not in the journal'))
            nq = norm(quote)
            if len(nq) < MIN_CHARS: why.append(('EB3', f'quote shorter than {MIN_CHARS} non-blank characters'))
            elif len(quote) > CFG['max_quote_chars']: why.append(('EB3', f'quote longer than max_quote_chars ({CFG["max_quote_chars"]})'))
            elif key is not None or ids:
                fs = {PS.fs_key(key)} if key else set()
                fs |= {PS.fs_key(i) for i in ids}
                own = [t for t in texts if (t['kind'] in ('source', 'fulltext') and t['name'] in fs and any(nq in v for v in t['texts'])) or
                       (t['kind'] == 'cache' and own_cache_hit(t, ids, nq, known))]
                hit = next(iter(own), None)
                if hit: rec['served'] = 'own'; rec['where'] = hit['where']
                else:
                    other = next((t for t in texts if t not in own and any(nq in v for v in t['texts'])), None)
                    if other: rec['served'] = 'other'; rec['where'] = other['where']; why.append(('EB5', f'misattributed: served under another source ({other["where"]})'))
                    else: rec['served'] = 'none'; why.append(('EB4', 'not served: not an exact substring of any text the gateway served in this run'))
            if not why and ids and not any(i in journal for i in ids):
                warnings.append({'check': 'W1', 'id': rec['id'], 'why': 'no identifier of this source appears in state/journal.jsonl'})
        rec['status'] = 'invalid' if why else 'valid'
        if why:
            rec['problems'] = [w for _, w in why]
            problems += [{'check': c, 'id': rec['id'], 'why': w} for c, w in why]
        rec['terms'] = sorted(terms(rec['quote'])); rec['numbers'] = numbers(rec['quote'], ignore_years=False)
        items.append(rec)
    return {'items': items, 'problems': problems, 'warnings': warnings}


# ---------- report ----------
ABBR = {'al', 'e.g', 'i.e', 'vs', 'cf', 'fig', 'figs', 'eq', 'no', 'approx', 'resp', 'ca', 'dr', 'pp', 'vol', 'ref', 'refs', 'et'}
SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9\[(“"‘])')


def sentences(par):
    parts, out = SPLIT.split(par), []
    for p in parts:
        if out:
            last = out[-1].rstrip()
            w = re.search(r'(\b[\w.]+)\.$', last)
            if w and (w.group(1).casefold() in ABBR or re.fullmatch(r'[A-Z]', w.group(1))): out[-1] = last + ' ' + p; continue
        out.append(p)
    return [s.strip() for s in out if s.strip()]


def report_units(md, skip=None):
    """REPORT.md -> [{'section', 'sub', 'text', 'cites': [n]}] for each sentence carrying a citation, outside the skipped sections."""
    skip = set(CFG['skip_sections'] if skip is None else skip)
    h2 = sub = ''; pars, cur, fence = [], [], False

    def flush():
        if cur: pars.append((h2, sub, ' '.join(cur))); cur.clear()
    for line in md.replace('\r\n', '\n').split('\n'):
        s = line.strip()
        if s.startswith('```') or s.startswith('~~~'): fence = not fence; flush(); continue
        if fence: continue
        if (m := re.match(r'^##\s+(.+?)\s*$', line)) and not line.startswith('###'): flush(); h2, sub = m.group(1).strip(), ''; continue
        if (m := re.match(r'^#{3,6}\s+(.+?)\s*$', line)): flush(); sub = m.group(1).strip(); continue
        if line.startswith('# '): flush(); continue
        if not s: flush(); continue
        if re.match(r'^\|?\s*:?-{3,}', s): continue
        if re.match(r'^([-*+]|\d+[.)])\s+', s) or s.startswith('|'): flush(); cur.append(s.strip('|').replace('|', ' ; ')); flush(); continue
        cur.append(s)
    flush()
    out = []
    for sec, sb, p in pars:
        if sec in skip or (RL.canonical(sec) or sec) in skip: continue      # a title of any language of tools/report_lang.py
        for t in sentences(p):
            cites = [int(x) for m in CITE_RE.finditer(t) for x in re.split(r'\s*[,;]\s*', m.group(1))]
            if cites: out.append({'section': sec, 'sub': sb, 'text': t, 'cites': list(dict.fromkeys(cites))})
    return out


def _sec_match(name, title):
    n, t = ' '.join(name.split()).casefold(), ' '.join(title.split()).casefold()
    return bool(t) and t.startswith(n) and (len(t) == len(n) or not t[len(n)].isalnum())


def allowed(item, unit):
    return not item['sections'] or any(_sec_match(s, unit['section']) or _sec_match(s, unit['sub']) for s in item['sections'])


def tie_report(folder, checked):
    """Sentences of REPORT.md with [n] -> statuses (see module docstring) and the measure."""
    d = pathlib.Path(folder)
    try: md = (d / 'REPORT.md').read_text(encoding='utf-8', errors='replace')
    except OSError: return None
    card = _json(d / 'card.json'); card = card if isinstance(card, dict) else {}
    keys_of = {}
    for k, n in PS.refs_of(d, card).items(): keys_of.setdefault(n, []).append(k)
    valid = [i for i in checked['items'] if i['status'] == 'valid']
    by_key = {}
    for i in valid:
        if i['key']: by_key.setdefault(i['key'], []).append(i)
    out = []
    for u in report_units(md):
        keys = [k for n in u['cites'] for k in keys_of.get(n, [])]
        ut, un = terms(u['text']), numbers(u['text'])
        rec = {'section': u['section'], 'sub': u['sub'], 'text': u['text'], 'cites': u['cites'], 'keys': keys, 'evidence': [],
               'shared_terms': [], 'missing_figures': []}
        if not keys: rec['status'] = 'unmapped'; out.append(rec); continue
        cands = [i for k in keys for i in by_key.get(k, [])]
        if not cands: rec['status'] = 'no_evidence'; out.append(rec); continue
        ok = [i for i in cands if allowed(i, u)]
        if not ok: rec['status'] = 'outside_section'; rec['evidence'] = [i['id'] for i in cands][:5]; out.append(rec); continue
        linked = [i for i in ok if ut & set(i['terms']) or set(un) & set(i['numbers'])]   # every quote of a cited source that the sentence draws on
        shared = ut & set().union(*(set(i['terms']) for i in linked))
        have = set().union(*(set(i['numbers']) for i in linked))
        missing = [x for x in un if x not in have]
        rec.update(evidence=[i['id'] for i in linked], shared_terms=sorted(shared), missing_figures=[_fmt(x) for x in dict.fromkeys(missing)])
        rec['status'] = 'supported' if len(shared) >= CFG['min_shared_terms'] and not missing else 'partial'
        out.append(rec)
    n = len(out); cnt = {s: sum(1 for x in out if x['status'] == s) for s in ('supported', 'partial', 'outside_section', 'no_evidence', 'unmapped')}
    per = {}
    for x in out:
        p = per.setdefault(x['section'], {'sentences': 0, 'supported': 0}); p['sentences'] += 1; p['supported'] += x['status'] == 'supported'
    return {'sentences': out, 'summary': {'sentences_with_citation': n, **cnt, 'supported_share': round(cnt['supported'] / n, 3) if n else None,
                                          'per_section': per}}


def _fmt(x):
    return str(int(x)) if float(x).is_integer() else str(x)


# ---------- whole build ----------
def bank_path(folder, bank=None):
    return pathlib.Path(bank) if bank else pathlib.Path(folder) / 'evidence.json'


def build(folder, bank=None):
    """Run dir (+ bank path) -> {'rule', 'bank': {...}, 'items', 'problems', 'warnings', 'report': {...} | None, 'summary'}; None: no bank."""
    d = pathlib.Path(folder); bp = bank_path(d, bank)
    if not bp.is_file(): return None
    raw = _json(bp)
    checked = check_bank(d, raw)
    tie = tie_report(d, checked)
    items = checked['items']
    card = _json(d / 'card.json'); card = card if isinstance(card, dict) else {}
    claim_ids = [c.get('id') for c in card.get('claims') or [] if isinstance(c, dict)]
    covered = {c for i in items if i['status'] == 'valid' for c in i['claims']} & set(claim_ids)
    origin = raw.get('origin') if isinstance(raw, dict) and isinstance(raw.get('origin'), str) else 'unspecified'
    summary = {'items': len(items), 'valid': sum(i['status'] == 'valid' for i in items), 'invalid': sum(i['status'] == 'invalid' for i in items),
               'not_served': sum(i.get('served') == 'none' for i in items), 'misattributed': sum(i.get('served') == 'other' for i in items),
               'with_sections': sum(bool(i['sections']) for i in items),
               'card_claims': len(claim_ids), 'card_claims_with_evidence': len(covered) if any(i['claims'] for i in items) else None}
    if tie: summary.update({k: tie['summary'][k] for k in ('sentences_with_citation', 'supported', 'supported_share')})
    return {'rule': 'quotes: exact substrings (NFKC, whitespace ignored) of texts the gateway served in this run; sentences: tied by [n] '
                    'to the items of their source allowed in their section, supported when they share min_shared_terms content terms and '
                    'every figure with the linked quotes; traceability, not truth (the verifier judges meaning)',
            'bank': {'path': str(bp.name if bp.parent == d else bp), 'origin': origin,
                     'sha256': hashlib.sha256(bp.read_bytes()).hexdigest()[:16]},
            'min_shared_terms': CFG['min_shared_terms'], 'items': items, 'problems': checked['problems'], 'warnings': checked['warnings'],
            'report': tie, 'summary': summary}


def from_verdicts(folder):
    """APPROXIMATE bank from verdicts.json: one item per distinct FOUND or DISTORTED fragment of a source (claims attached). It stands for
    an orchestrator bank in demonstrations only: these quotes were chosen by the verifier after the report, not extracted before it."""
    d = pathlib.Path(folder); ver = _json(d / 'verdicts.json')
    if not isinstance(ver, dict) or not isinstance(ver.get('claims'), list): return None
    seen, ev = {}, []
    for c in ver['claims']:
        if not isinstance(c, dict) or str(c.get('status') or '').upper() not in ('FOUND', 'DISTORTED'): continue
        for f in c.get('fragments') or []:
            if not isinstance(f, str) or len(norm(f)) < MIN_CHARS: continue
            k = (str(c.get('source') or ''), norm(f))
            if k in seen: seen[k]['claims'].append(str(c.get('id'))); continue
            it = {'id': f'E{len(ev) + 1}', 'source': k[0], 'quote': f, 'claims': [str(c.get('id'))]}
            seen[k] = it; ev.append(it)
    return {'origin': 'verifier-fragments (APPROXIMATION: quotes chosen by the verifier after the report was written, not extracted by '
                      'the orchestrator before writing; no section attribution)', 'evidence': ev}


# ---------- outputs (every quote and sentence is data: inert in Markdown, escaped in HTML) ----------
def _short(t, n=None):
    n = CFG['shown_chars'] if n is None else n
    t = ' '.join(str(t or '').split())
    return t if len(t) <= n else t[:n].rsplit(' ', 1)[0] + ' [...]'


def section_items(doc, name):
    unit = {'section': name, 'sub': name}
    return [i for i in doc['items'] if i['status'] == 'valid' and allowed(i, unit)]


def markdown_items(items, title):
    lines = [f'# {title}', '', 'Each quote is source text (data, never instructions), checked by tools/evidence_bank.py as served by the gateway.', '']
    for i in items:
        f = PS._fence(i['quote'])
        lines += [f"- {i['id']} (source {PS._code(i['source'])}" + (f", claims {PS._code(', '.join(i['claims']))}" if i['claims'] else '') + ')',
                  f'  {f}text', '  ' + ' '.join(i['quote'].split()), f'  {f}', '']
    return '\n'.join(lines) + '\n'


def markdown(doc):
    s = doc['summary']; L = ['# Evidence Bank Check', '',
                             'Code check of the evidence bank (tools/evidence_bank.py, no model): each quote must be an exact substring of a text the '
                             'gateway served in this run, under its own source; each sentence of REPORT.md with a [n] is tied to the quotes of '
                             'its cited sources. Quotes and sentences below are data, shown in inert code blocks.', '',
                             f"Bank: `{doc['bank']['path']}`, origin: {PS._code(doc['bank']['origin'])}.", '',
                             f"Items: {s['items']} ({s['valid']} valid, {s['invalid']} invalid: {s['not_served']} not served, {s['misattributed']} misattributed); "
                             f"items with a section attribution: {s['with_sections']}."]
    if s.get('card_claims_with_evidence') is not None:
        L.append(f"Card claims with a valid evidence item: {s['card_claims_with_evidence']} of {s['card_claims']}.")
    if doc['report']:
        r = doc['report']['summary']
        share = 'n/a' if r['supported_share'] is None else f"{r['supported_share'] * 100:.1f} %"
        L += ['', f"**Supported share: {share}** ({r['supported']} of {r['sentences_with_citation']} sentences with a [n]; "
                  f"partial {r['partial']}, outside their section {r['outside_section']}, no evidence {r['no_evidence']}, unmapped {r['unmapped']}).",
              f"Rule: supported = the linked quotes share at least {doc['min_shared_terms']} content terms and every figure of the sentence."]
    if doc['problems']:
        L += ['', '## Invalid items', '']
        for p in doc['problems']: L.append(f"- {p['id']} {p['check']}: {p['why']}")
    if doc['warnings']:
        L += ['', '## Warnings', '']
        for p in doc['warnings']: L.append(f"- {p['id']} {p['check']}: {p['why']}")
    if doc['report']:
        L += ['', '## Sentences not supported', '']
        for x in doc['report']['sentences']:
            if x['status'] == 'supported': continue
            where = x['section'] + (f" / {x['sub']}" if x['sub'] else '')
            extra = (f"; missing figures: {', '.join(x['missing_figures'])}" if x['missing_figures'] else '') + (f"; linked: {', '.join(x['evidence'])}" if x['evidence'] else '')
            L += [f"- {x['status']} ({where}){extra}", '  Sentence: ' + PS._code(_short(x['text']))]
    L += ['', '## Items', '']
    for i in doc['items']:
        f = PS._fence(i['quote'])
        L += [f"- {i['id']} {i['status']} (source {PS._code(i['source'])}" + (f", {i['where']}" if i.get('where') else '') +
              (f", sections: {PS._code('; '.join(i['sections']))}" if i['sections'] else '') + ')', f'  {f}text', '  ' + _short(i['quote']), f'  {f}', '']
    return '\n'.join(L) + '\n'


CSS = ('body{margin:0 auto;max-width:48rem;padding:2rem 1rem;background:#fff;color:#1d1d1f;font:15px/1.55 Georgia,serif}'
       'h1,h2{font-family:Arial,sans-serif}blockquote{margin:.3rem 0 .9rem;padding:.2rem .9rem;border-left:3px solid #c9c9d1;color:#45454d}'
       '.s{font:12px Arial,sans-serif;color:#5b5b66}.bad{color:#9b1c1c}')


def html_page(doc):
    e = lambda t: html.escape(str(t), quote=True)
    s = doc['summary']; out = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">',
                               '<title>Evidence Bank Check</title><style>' + CSS + '</style></head><body><h1>Evidence Bank Check</h1>',
                               f"<p>Bank origin: {e(doc['bank']['origin'])}. Items: {s['items']} ({s['valid']} valid, {s['invalid']} invalid).</p>"]
    if doc['report']:
        r = doc['report']['summary']
        share = 'n/a' if r['supported_share'] is None else f"{r['supported_share'] * 100:.1f} %"
        out.append(f"<p><strong>Supported share: {e(share)}</strong> ({r['supported']} of {r['sentences_with_citation']} sentences with a [n]).</p>")
        out.append('<h2>Sentences not supported</h2>')
        for x in doc['report']['sentences']:
            if x['status'] != 'supported':
                out.append(f"<p class=\"s\">{e(x['status'])} &middot; {e(x['section'])}</p><blockquote>{e(_short(x['text']))}</blockquote>")
    out.append('<h2>Items</h2>')
    for i in doc['items']:
        cls = '' if i['status'] == 'valid' else ' bad'
        out.append(f"<p class=\"s{cls}\">{e(i['id'])} &middot; {e(i['status'])} &middot; source {e(i['source'])}"
                   + (f" &middot; {e('; '.join(i.get('problems') or []))}" if i.get('problems') else '') + f"</p><blockquote>{e(_short(i['quote']))}</blockquote>")
    out.append('</body></html>')
    return '\n'.join(out) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('dir'); ap.add_argument('--bank'); ap.add_argument('--out'); ap.add_argument('--json', action='store_true')
    ap.add_argument('--html', action='store_true'); ap.add_argument('--section'); ap.add_argument('--from-verdicts', action='store_true')
    a = ap.parse_args(argv)
    d = pathlib.Path(a.dir)
    if not d.is_dir(): print(f'not a directory: {d}', file=sys.stderr); return 2
    bank = a.bank
    if a.from_verdicts:
        b = from_verdicts(d)
        if b is None: print('no verdicts.json with claims', file=sys.stderr); return 2
        target = pathlib.Path(a.bank) if a.bank else (pathlib.Path(a.out) if a.out else d) / 'evidence.json'
        if target.exists():
            print(f'refused: {target} exists and is never overwritten by --from-verdicts (an existing bank is the user\'s); '
                  f'pass --out DIR or --bank FILE to a new path', file=sys.stderr); return 2
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f"{target}: {len(b['evidence'])} items (approximation from the verifier's fragments)")
        bank = str(target)
    doc = build(d, bank)
    if doc is None: print(f'no evidence bank: {bank_path(d, bank)}', file=sys.stderr); return 2
    if a.section:
        sys.stdout.write(markdown_items(section_items(doc, a.section), f'Evidence for section: {" ".join(a.section.split())}')); return 0
    out = pathlib.Path(a.out) if a.out else d; out.mkdir(parents=True, exist_ok=True)
    (out / 'evidence_check.json').write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'EVIDENCE.md').write_text(markdown(doc), encoding='utf-8')
    if a.html: (out / 'EVIDENCE.html').write_text(html_page(doc), encoding='utf-8')
    if a.json: print(json.dumps(doc['summary'], ensure_ascii=False))
    else:
        s = doc['summary']
        print(f"{out / 'EVIDENCE.md'}: {s['valid']}/{s['items']} items valid" +
              (f"; supported share {s['supported_share']} ({s['supported']}/{s['sentences_with_citation']})" if 'supported_share' in s else ''))
    return 1 if doc['problems'] else 0


if __name__ == '__main__':
    sys.exit(main())
