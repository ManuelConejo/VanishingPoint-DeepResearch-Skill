#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Mechanical contradiction candidates between sources: the optional contradiction hunt (SKILL.md "Contradiction hunt (optional, never by
default)"). Standard library, offline, no model call, no gateway call. It never filters, corrects or removes a claim: it shows candidates
to the reader, and the model judges them in the optional mode.

Passages compared (exact source text only, never a model's words):
  - each claim of verdicts.json whose status is in contradictions.statuses, through the verifier's fragments located in the text it read
    (DIR/sources/<KEY>/source.txt), widened to their sentence as tools/passages.py does; a claim without such a passage is counted, not compared;
  - each valid item of the evidence bank (DIR/evidence.json, checked by tools/evidence_bank.py), when it exists: its quote.
Same topic (pairs of passages from two different sources): they share at least contradictions.min_shared_terms content terms (text_terms
of tools/config.json, read on the passage and on the claim it supports), or one named entity (acronym, word mixing letters and digits, inner
capital) plus one term, or a sentence of REPORT.md cites both of their [n] (crossed [n]) plus one term.
Signals (read on the passages only, each near a shared term, within contradictions.window_words words):
  numbers    the same measure (a shared term in the context of both figures, same unit: %, or the same following word) with values that
             differ beyond their rounding (half a unit of the less precise figure) and contradictions.number_rel_tol;
  direction  one passage has an "up" word and the other a "down" word (contradictions.directions) about the same term;
  polarity   one passage has a negative marker (contradictions.polarity_negative) about a term the other states without one;
  decision   one passage has a "for" word and the other an "against" word (contradictions.decisions), for law;
  report     (supporting only, never alone) a sentence of REPORT.md that cites both [n] carries a contrast marker.
A pair with at least one of the first four signals is a candidate. Candidates are ranked (signal kinds, shared entities, crossed [n],
shared terms), at most contradictions.max_per_source_pair per pair of sources and contradictions.max_candidates in all; each has a
`key` (hash of its two passages) so that a judgment is never applied to another pair.
Judgment (the model, optional mode): DIR/contradictions-judged.json = {"judgments": [{"id": "C1", "key": "<key>", "verdict":
"disagreement" | "different-conditions" | "no-disagreement" | "unclear", "why": "..."}]}; checked by this tool (unknown id, stale key or
unknown verdict refused) and shown next to the candidate.
Outputs: DIR/CONTRADICTIONS.md (passages in inert fenced blocks), DIR/contradictions.json, and with --html DIR/CONTRADICTIONS.html
(every passage HTML-escaped, no script, no external resource).
Usage: contradictions.py DIR [--bank FILE] [--judgments FILE] [--out DIR] [--json] [--html]
Exit: 0 written (judgments valid or absent); 1 judgments refused (listed); 2 not a directory, or no verdicts.json and no bank.
Import: passages_of(dir, bank=None) -> [item]; candidates(items, cocited) -> [candidate]; build(dir, bank=None, judgments=None) -> dict;
markdown(doc); html_page(doc)."""
import argparse, hashlib, html, json, pathlib, re, sys, unicodedata

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evidence_bank as EB                                  # noqa: E402  (terms, numbers, report units, bank check)
import passages as PS                                       # noqa: E402  (locate, passage, refs_of, fs_key, _fence, _code)


def _config():
    try: c = json.loads((HERE / 'config.json').read_text(encoding='utf-8')).get('contradictions') or {}
    except (OSError, ValueError): c = {}
    low = lambda xs: [' '.join(str(x).casefold().split()) for x in xs or []]
    dirs, dec = c.get('directions') or {}, c.get('decisions') or {}
    return {'statuses': [s.upper() for s in c.get('statuses') or ['FOUND', 'DISTORTED', 'SOURCE-UNAVAILABLE', 'UNVERIFIED']],
            'min_shared_terms': int(c.get('min_shared_terms', 2)), 'window': int(c.get('window_words', 6)),
            'rel_tol': float(c.get('number_rel_tol', 0.0)), 'number_window': int(c.get('number_window_words', 3)),
            'labels': set(low(c.get('label_words') or [])), 'max_candidates': int(c.get('max_candidates', 40)),
            'max_per_pair': int(c.get('max_per_source_pair', 2)), 'contrast': low(c.get('contrast_markers')),
            'up': low(dirs.get('up')), 'down': low(dirs.get('down')), 'negative': low(c.get('polarity_negative')),
            'for': low(dec.get('for')), 'against': low(dec.get('against')),
            'verdicts': list(c.get('verdicts') or ['disagreement', 'different-conditions', 'no-disagreement', 'unclear'])}


CFG = _config()
TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_][\w'’]*|%")
ENTITY = re.compile(r"\b(?:[A-Z]{2,}[A-Za-z0-9]*|[A-Za-z]+-?\d[\w-]*|[a-z]+[A-Z]\w*)\b")


def _json(p):
    try: return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError): return None


def tokens(text):
    """[(lower token, stem or None, is_number, glued)] of a passage; glued = a figure that is part of a label or a name, not a measure:
    touching a letter or one of ( / @ _ ^ : on either side ('1.7B', 'Qwen3-8B', '99(2)', '7-point'), or preceded by a label word
    (contradictions.label_words: 'Article 16', 'Table 2')."""
    text = unicodedata.normalize('NFKC', text); out = []
    for m in TOKEN.finditer(text):
        t = m.group(0); low = t.casefold()
        if t[0].isdigit():
            c0 = text[m.start() - 1] if m.start() else ' '; c1 = text[m.end()] if m.end() < len(text) else ' '
            c2 = text[m.end() + 1] if m.end() + 1 < len(text) else ' '; cm = text[m.start() - 2] if m.start() > 1 else ' '
            glued = (c0.isalpha() or c1.isalpha() or c0 in '/@_^:' or c1 in '(/@_^:' or (c0 == '(' and c1 == ')')
                     or (c1 == '-' and c2.isalpha()) or (c0 == '-' and cm.isalnum()))
            prev = next((x for x in reversed(out) if not x[2]), None)
            if prev and out and out[-1] is prev and prev[0] in CFG['labels']: glued = True
            out.append((low, None, True, glued)); continue
        st = EB.stem(low)
        ok = len(st) >= EB.CFG['min_term_chars'] and st not in EB.CFG['stopwords']
        out.append((low, st if ok else None, False, False))
    return out


def entities(text):
    """Named entities of a text, lower-cased: acronyms, words mixing letters and digits, words with an inner capital."""
    return {e.casefold() for e in ENTITY.findall(text) if e.casefold() not in EB.CFG['stopwords']}


def _phrases(toks, phrases):
    """Positions where one of the phrases (lower-case word sequences) starts."""
    words = [t[0] for t in toks]; out = []
    for ph in phrases:
        p = ph.split()
        for i in range(len(words) - len(p) + 1):
            if words[i:i + len(p)] == p: out.append((i, ph))
    return out


def _context(toks, i, w=None):
    w = CFG['window'] if w is None else w
    return {t[1] for t in toks[max(0, i - w): i + w + 1] if t[1]}


def _value(raw):
    """'62.8' / '62,8' / '1,000' -> (value, half-unit of rounding)."""
    if re.fullmatch(r'\d{1,3}(?:,\d{3})+', raw): return float(raw.replace(',', '')), 0.5
    raw = raw.replace(',', '.')
    if raw.count('.') > 1: return None
    dec = len(raw.split('.')[1]) if '.' in raw else 0
    return float(raw), 0.5 * 10 ** (-dec)


def figures(toks):
    """[(value, half_unit, unit, context terms, shown text)] for each measure figure of a passage (labels, names and years 1800-2100
    skipped). Context = content terms within contradictions.number_window_words words before the figure and the word after its unit."""
    out = []
    for i, (low, _, isnum, glued) in enumerate(toks):
        if not isnum or glued: continue
        v = _value(low)
        if v is None: continue
        if v[1] == 0.5 and 1800 <= v[0] <= 2100 and len(low) == 4: continue
        nxt = toks[i + 1] if i + 1 < len(toks) else ('', None, False, False)
        unit = '%' if nxt[0] in ('%', 'percent') else (nxt[1] or '') if not nxt[2] else ''
        w = CFG['number_window']
        ctx = {t[1] for t in toks[max(0, i - w): i + 3] if t[1]} - ({unit} if unit else set())
        out.append((v[0], v[1], unit, ctx, low + (' %' if unit == '%' else f' {nxt[0]}' if unit else '')))
    return out


def _item(source, key, ref, cid, status, text, claim, origin):
    toks = tokens(text)
    return {'source': source, 'key': key, 'ref': ref, 'claim_id': cid, 'status': status, 'passage': text, 'claim': claim, 'origin': origin,
            'terms': EB.terms(text) | EB.terms(claim), 'entities': entities(text) | entities(claim), 'toks': toks, 'figures': figures(toks)}


def passages_of(folder, bank=None):
    """Items to compare and the count of claims without an exact passage."""
    d = pathlib.Path(folder)
    card = _json(d / 'card.json'); card = card if isinstance(card, dict) else {}
    refs = PS.refs_of(d, card)
    ver = _json(d / 'verdicts.json'); items, without = [], 0
    claims_text = {c.get('id'): c.get('text', '') for c in card.get('claims') or [] if isinstance(c, dict)}
    texts = {}
    for c in (ver.get('claims') if isinstance(ver, dict) and isinstance(ver.get('claims'), list) else []):
        if not isinstance(c, dict) or str(c.get('status') or '').upper() not in CFG['statuses']: continue
        key = str(c.get('source') or '')
        if key not in texts:
            f = d / 'sources' / PS.fs_key(key) / 'source.txt'
            texts[key] = f.read_text(encoding='utf-8', errors='replace') if f.is_file() else None
        shown = []
        for fr in c.get('fragments') or []:
            sp = PS.locate(fr, texts[key]) if texts[key] and isinstance(fr, str) else None
            if sp:
                p = PS.passage(texts[key], *sp)['text']
                if p not in shown: shown.append(p)
        if not shown: without += 1; continue
        items.append(_item(key, key, refs.get(key), str(c.get('id')), str(c.get('status')).upper(), ' '.join(shown),
                           str(c.get('text') or claims_text.get(c.get('id')) or ''), 'verifier fragment, widened to its sentence'))
    bp = EB.bank_path(d, bank); bank_items = 0
    if bp.is_file():
        chk = EB.check_bank(d, _json(bp))
        for i in chk['items']:
            if i['status'] != 'valid': continue
            k0 = i['key'] or i['source']; nq = EB.norm(i['quote'])
            if any(x['key'] == k0 and nq in EB.norm(x['passage']) for x in items): continue   # already compared through a verifier passage
            bank_items += 1
            items.append(_item(i['source'], k0, refs.get(k0), i['id'], 'evidence', ' '.join(i['quote'].split()), '', 'evidence bank quote'))
    return items, {'claims_without_passage': without, 'bank_items': bank_items}


def cocited(folder):
    """{frozenset({n, m}): contrast marker or ''} for each pair of [n] cited in one sentence of REPORT.md."""
    try: md = (pathlib.Path(folder) / 'REPORT.md').read_text(encoding='utf-8', errors='replace')
    except OSError: return {}
    out = {}
    for u in EB.report_units(md):
        low = ' ' + ' '.join(re.findall(r"[\w'’]+", u['text'].casefold())) + ' '
        mark = next((m for m in CFG['contrast'] if f' {m} ' in low), '')
        for a in u['cites']:
            for b in u['cites']:
                if a < b:
                    k = frozenset((a, b))
                    if mark or k not in out: out[k] = mark or out.get(k, '')
    return out


def _near(toks, positions, shared):
    """Shared terms within the window of any of the positions."""
    return {t for i, _ in positions for t in _context(toks, i)} & shared


def signals(a, b, shared):
    out = []
    groups = {}
    for side, x in ((0, a), (1, b)):
        for f in x['figures']:
            for t in f[3] & shared:
                groups.setdefault((f[2], t), ([], []))[side].append(f)
    for (unit, t), (fa, fb) in sorted(groups.items(), key=lambda g: (g[0][0] != '%', g[0])):
        if not fa or not fb: continue
        same = lambda p, q: abs(p[0] - q[0]) <= max(p[1], q[1]) + CFG['rel_tol'] * max(abs(p[0]), abs(q[0]))
        if any(same(p, q) for p in fa for q in fb): continue          # one figure agrees: the measure is not in conflict
        out.append({'kind': 'numbers', 'a': ', '.join(dict.fromkeys(f[4] for f in fa)), 'b': ', '.join(dict.fromkeys(f[4] for f in fb)),
                    'about': [t], 'percent': unit == '%'})
        break
    for x, y, kind in (('up', 'down', 'direction'), ('for', 'against', 'decision')):
        for p, q in ((a, b), (b, a)):
            px, qy = _phrases(p['toks'], CFG[x]), _phrases(q['toks'], CFG[y])
            about = _near(p['toks'], px, shared) & _near(q['toks'], qy, shared)
            if about:
                ws = (sorted({w for _, w in px})[:3], sorted({w for _, w in qy})[:3])
                out.append({'kind': kind, 'a': ', '.join(ws[0] if p is a else ws[1]), 'b': ', '.join(ws[1] if p is a else ws[0]), 'about': sorted(about)[:4]})
                break
    na, nb = _phrases(a['toks'], CFG['negative']), _phrases(b['toks'], CFG['negative'])
    for p, q, np_, nq in ((a, b, na, nb), (b, a, nb, na)):
        about = _near(p['toks'], np_, shared) - _near(q['toks'], nq, shared)
        about = {t for t in about if any(tk[1] == t for tk in q['toks'])}
        if about:
            out.append({'kind': 'polarity', 'a': ', '.join(sorted({w for _, w in np_})[:3]) if p is a else 'affirmative',
                        'b': ', '.join(sorted({w for _, w in np_})[:3]) if p is b else 'affirmative', 'about': sorted(about)[:4]})
            break
    return out


def candidates(items, co):
    found = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if a['key'] == b['key']: continue
            shared = a['terms'] & b['terms']; ents = a['entities'] & b['entities']
            pair = frozenset((a['ref'], b['ref'])) if a['ref'] is not None and b['ref'] is not None else None
            crossed = pair in co if pair else False
            if not (len(shared) >= CFG['min_shared_terms'] or (shared and (ents or crossed))): continue
            sig = signals(a, b, shared)
            if not sig: continue
            if crossed and co.get(pair): sig.append({'kind': 'report', 'a': co[pair], 'b': '', 'about': []})
            kinds = {s['kind'] for s in sig if s['kind'] != 'report'}
            score = (len(kinds), any(s.get('percent') for s in sig), len(ents), crossed, len(shared))
            found.append({'a': a, 'b': b, 'signals': sig, 'shared_terms': sorted(shared)[:8], 'shared_entities': sorted(ents)[:5],
                          'crossed': crossed, 'score': score})
    found.sort(key=lambda c: c['score'], reverse=True)
    per, out = {}, []
    for c in found:
        pk = frozenset((c['a']['key'], c['b']['key']))
        if per.get(pk, 0) >= CFG['max_per_pair']: continue
        per[pk] = per.get(pk, 0) + 1; out.append(c)
        if len(out) >= CFG['max_candidates']: break
    return out, len(found)


def _side(x):
    return {k: x[k] for k in ('source', 'ref', 'claim_id', 'status', 'origin', 'passage', 'claim')}


def check_judgments(raw, cands):
    by_id = {c['id']: c for c in cands}; ok, pb = {}, []
    if raw is None: return ok, pb
    if not isinstance(raw, dict) or not isinstance(raw.get('judgments'), list): return ok, [{'id': None, 'why': 'not an object with a "judgments" list'}]
    for k, j in enumerate(raw['judgments']):
        jid = j.get('id') if isinstance(j, dict) else None
        if not isinstance(j, dict) or jid not in by_id: pb.append({'id': f'#{k + 1}', 'why': 'unknown candidate id'}); continue
        if j.get('key') != by_id[jid]['key']: pb.append({'id': jid, 'why': 'stale: key does not match the candidate (the passages changed)'}); continue
        if j.get('verdict') not in CFG['verdicts']: pb.append({'id': jid, 'why': f'verdict not in {CFG["verdicts"]}'}); continue
        ok[jid] = {'verdict': j['verdict'], 'why': ' '.join(str(j.get('why') or '').split())[:600]}
    return ok, pb


def build(folder, bank=None, judgments=None):
    d = pathlib.Path(folder)
    if not (d / 'verdicts.json').is_file() and not EB.bank_path(d, bank).is_file(): return None
    items, counts = passages_of(d, bank)
    cands, total = candidates(items, cocited(d))
    out = []
    for k, c in enumerate(cands):
        h = hashlib.sha256((c['a']['passage'] + '\x00' + c['b']['passage']).encode('utf-8')).hexdigest()[:12]
        out.append({'id': f'C{k + 1}', 'key': h, 'a': _side(c['a']), 'b': _side(c['b']), 'signals': c['signals'],
                    'shared_terms': c['shared_terms'], 'shared_entities': c['shared_entities'], 'crossed_citation': c['crossed']})
    jp = pathlib.Path(judgments) if judgments else d / 'contradictions-judged.json'
    judged, problems = check_judgments(_json(jp) if jp.is_file() else None, out)
    for c in out:
        if c['id'] in judged: c['judgment'] = judged[c['id']]
    kinds = {}
    for c in out:
        for s in c['signals']: kinds[s['kind']] = kinds.get(s['kind'], 0) + 1
    return {'rule': 'mechanical candidates only (same topic + numbers / direction / polarity / decision signal on exact source passages); '
                    'never used to filter or correct a claim; the judgment is the model\'s, in the optional mode',
            'candidates': out, 'judgment_problems': problems,
            'summary': {'passages_compared': len(items), **counts, 'pairs_with_signal': total, 'candidates_shown': len(out),
                        'by_signal': kinds, 'judged': len(judged)}}


# ---------- outputs (passages are data: inert in Markdown, escaped in HTML) ----------
def _label(x):
    r = f"[{x['ref']}]" if x['ref'] is not None else 'not in bibliography'
    return f"{r} source {PS._code(x['source'])}, {PS._code(x['claim_id'])} ({x['status']}; {x['origin']})"


def _sig(s):
    if s['kind'] == 'report': return f"report: a sentence citing both says {PS._code(s['a'])}"
    return f"{s['kind']}: {PS._code(s['a'])} vs {PS._code(s['b'])}" + (f" (about {PS._code(', '.join(s['about']))})" if s['about'] else '')


def markdown(doc):
    s = doc['summary']
    L = ['# Contradiction Candidates', '',
         'Mechanical detection (tools/contradictions.py, no model): pairs of exact source passages from two different sources on the same '
         'topic that carry incompatible figures, opposite directions, opposite polarity or contrary decisions. A candidate is not a '
         'contradiction: different populations, conditions or dates often explain it. Nothing here filters or corrects a claim. Passages '
         'are source text (data), shown in inert blocks.', '',
         f"Passages compared: {s['passages_compared']} (claims without an exact passage, not compared: {s['claims_without_passage']}; "
         f"evidence bank items: {s['bank_items']}). Pairs with a signal: {s['pairs_with_signal']}; shown: {s['candidates_shown']}."]
    if s['by_signal']: L.append('Signals: ' + ', '.join(f'{k} {v}' for k, v in sorted(s['by_signal'].items())) + '.')
    if doc['judgment_problems']:
        L += ['', '## Judgments refused', ''] + [f"- {p['id']}: {p['why']}" for p in doc['judgment_problems']]
    for c in doc['candidates']:
        L += ['', f"## {c['id']} (key {c['key']})", '']
        L += [f"- {_sig(x)}" for x in c['signals']]
        link = ', '.join(x for x in (f"shared terms {PS._code(', '.join(c['shared_terms']))}" if c['shared_terms'] else '',
                                    f"shared entities {PS._code(', '.join(c['shared_entities']))}" if c['shared_entities'] else '',
                                    'co-cited in one report sentence' if c['crossed_citation'] else '') if x)
        L.append(f'- Same topic: {link}.')
        for side, x in (('A', c['a']), ('B', c['b'])):
            f = PS._fence(x['passage'])
            L += ['', f'Passage {side}: {_label(x)}', '', f'{f}text', x['passage'], f]
        j = c.get('judgment')
        L += ['', f"Judgment: {PS._code(j['verdict'])}: {PS._code(j['why']) if j['why'] else ''}" if j else 'Judgment: pending (the model judges in the optional mode).']
    if not doc['candidates']: L += ['', 'No candidate.']
    return '\n'.join(L) + '\n'


def html_page(doc):
    e = lambda t: html.escape(str(t), quote=True)
    s = doc['summary']
    out = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">',
           '<title>Contradiction Candidates</title><style>' + EB.CSS + '</style></head><body><h1>Contradiction Candidates</h1>',
           f"<p>Mechanical candidates, not judgments; nothing here filters a claim. Passages compared: {s['passages_compared']}; shown: {s['candidates_shown']}.</p>"]
    for c in doc['candidates']:
        out.append(f"<h2>{e(c['id'])}</h2><p class=\"s\">" + ' &middot; '.join(
            e(f"{x['kind']}: {x['a']} vs {x['b']}" if x['kind'] != 'report' else f"report: {x['a']}") for x in c['signals']) + '</p>')
        for side, x in (('A', c['a']), ('B', c['b'])):
            ref = f"[{x['ref']}]" if x['ref'] is not None else ''
            out.append(f"<p class=\"s\">Passage {side}: {e(ref)} {e(x['source'])} {e(x['claim_id'])} ({e(x['status'])})</p><blockquote>{e(x['passage'])}</blockquote>")
        if c.get('judgment'): out.append(f"<p class=\"s\">Judgment: {e(c['judgment']['verdict'])}: {e(c['judgment']['why'])}</p>")
    out.append('</body></html>')
    return '\n'.join(out) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('dir'); ap.add_argument('--bank'); ap.add_argument('--judgments'); ap.add_argument('--out')
    ap.add_argument('--json', action='store_true'); ap.add_argument('--html', action='store_true')
    a = ap.parse_args(argv)
    d = pathlib.Path(a.dir)
    if not d.is_dir(): print(f'not a directory: {d}', file=sys.stderr); return 2
    doc = build(d, a.bank, a.judgments)
    if doc is None: print('no verdicts.json and no evidence bank', file=sys.stderr); return 2
    out = pathlib.Path(a.out) if a.out else d; out.mkdir(parents=True, exist_ok=True)
    (out / 'contradictions.json').write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'CONTRADICTIONS.md').write_text(markdown(doc), encoding='utf-8')
    if a.html: (out / 'CONTRADICTIONS.html').write_text(html_page(doc), encoding='utf-8')
    s = doc['summary']
    print(json.dumps(s, ensure_ascii=False) if a.json else
          f"{out / 'CONTRADICTIONS.md'}: {s['candidates_shown']} candidates ({s['pairs_with_signal']} pairs with a signal, {s['passages_compared']} passages)")
    return 1 if doc['judgment_problems'] else 0


if __name__ == '__main__':
    sys.exit(main())
