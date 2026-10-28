#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Cited passages of a run: for each claim of verdicts.json, the exact passage of its source that the verifier's machine-checked fragments
point to, taken by this code from the text the verifier read (DIR/sources/<KEY>/source.txt), never written by a model. Standard library, offline.

Rule (no invented quotation): a passage is shown only when the verifier gave fragments for a FOUND or DISTORTED claim AND the fragment is
found in the kept source text with whitespace ignored; what is shown is then the source's own characters at that place (whitespace runs
collapsed to one space), so the displayed passage is always an exact substring of the source after whitespace normalisation. The passage
is widened to the enclosing sentence when that sentence fits in config `passages.max_chars`, else it is the fragment alone (a fragment
longer than max_chars is cut at a word boundary and flagged `truncated`; the shown text is still a prefix of the source span). Any other
case gives no passage and a reason (source not read, abstract only, ABSENT, INVALID, no verdict, fragment not matched in the kept text).
Origin of each passage: the identifier of the source, and what was read: `full text` (with version and method when the fetch receipt
meta.json is kept next to it or in state/fulltext/ with the same text) or `record + abstract` (gateway notice, record.json kept).
Claim -> bibliography [n]: card key S<n> when [n] exists and does not name another document, else the entry sharing an identifier.

Usage: passages.py RUN_DIR [--out DIR] [--json]   -> DIR/passages.json and DIR/PASSAGES.md (also written by export_data.py; the
HTML blocks under each bibliography entry are drawn by export_report.py). Exit 0; 2 when RUN_DIR has no verdicts.json.
Import: build(dir) -> dict; locate(fragment, text) -> (start, end) | None; passage(text, start, end, max_chars) -> dict; markdown(doc) -> str."""
import argparse, json, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE / 'verifier'))
from citation_check import MIN_CHARS                        # noqa: E402  (same minimum fragment size as the mechanical check)

try:
    CFG = json.loads((HERE / 'config.json').read_text(encoding='utf-8')).get('passages', {})
except (OSError, ValueError):
    CFG = {}
MAX_CHARS = int(CFG.get('max_chars', 300))
MAX_PER_CLAIM = int(CFG.get('max_per_claim', 4))
PROOF = {'FOUND', 'DISTORTED'}
SENT_END = re.compile(r'[.!?]["\'’”)\]]*(?=\s|$)|\n[ \t]*\n')
WS = re.compile(r'\s+')


def fs_key(c):
    """Same file-system key as tools/verifier.py (sources/<KEY>/)."""
    s = re.sub(r'[^\w.-]+', '_', str(c or '')).strip('.')
    return s or 'source'


def locate(fragment, text):
    """(start, end) in text of the fragment, whitespace ignored on both sides; None when absent or shorter than MIN_CHARS non-blank."""
    f = WS.sub('', str(fragment or ''))
    if len(f) < MIN_CHARS: return None
    idx = [i for i, ch in enumerate(text) if not ch.isspace()]
    pos = ''.join(text[i] for i in idx).find(f)
    if pos < 0: return None
    return idx[pos], idx[pos + len(f) - 1] + 1


def _collapse(s):
    return WS.sub(' ', s)


def passage(text, start, end, max_chars=None):
    """Source span [start, end) -> {'text', 'marks': [[a, b]], 'truncated'}: the enclosing sentence when it fits in max_chars, else the
    span alone (cut at a word boundary if longer). marks = the verified fragment inside the shown text."""
    max_chars = MAX_CHARS if max_chars is None else max_chars
    b = 0
    for m in SENT_END.finditer(text, 0, start):
        b = m.end()
    m = SENT_END.search(text, max(start, end - 1))
    e = m.end() if m else len(text)
    before, frag, after = _collapse(text[b:start]).lstrip(), _collapse(text[start:end]), _collapse(text[end:e]).rstrip()
    if len(before) + len(frag) + len(after) <= max_chars:
        return {'text': before + frag + after, 'marks': [[len(before), len(before) + len(frag)]], 'truncated': False}
    if len(frag) <= max_chars:
        return {'text': frag, 'marks': [[0, len(frag)]], 'truncated': False}
    cut = frag[:max_chars]
    cut = cut[:cut.rfind(' ')] if ' ' in cut else cut
    return {'text': cut, 'marks': [[0, len(cut)]], 'truncated': True}


def _json(p):
    try: return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError): return None


def _ident(desc, key):
    """Identifier of a card source (the first VP identifier field it carries, as export_data reads them), else the key when it is one."""
    try:
        import export_data as X
        ids = X._src_ids(desc)
    except Exception:
        ids = []
    if ids: return ids[0]
    if isinstance(desc, dict) and isinstance(desc.get('code'), str) and desc['code']: return f"code:{desc['code']}"
    return str(key) if re.match(r'^[a-z]+:\S+$', str(key)) else ''


def origin(d, key, claim_origin, ident):
    """What the verifier read for this source, from the files kept in the run: (origin dict, text or None)."""
    sd = d / 'sources' / fs_key(key)
    src = sd / 'source.txt'
    if claim_origin == 'missing': return {'kind': 'not read', 'id': ident}, None
    if not src.is_file(): return {'kind': 'not kept', 'id': ident}, None
    text = src.read_text(encoding='utf-8', errors='replace')
    rec = _json(sd / 'record.json') if (sd / 'record.json').is_file() else None
    if rec is not None or claim_origin == 'abstract':
        r = rec.get('results') if isinstance(rec, dict) else None
        rid = r.get('id') if isinstance(r, dict) and isinstance(r.get('id'), str) else ''
        return {'kind': 'record + abstract', 'id': rid or ident}, text
    o = {'kind': 'full text', 'id': ident}
    for meta in (sd / 'meta.json', d / 'state' / 'fulltext' / fs_key(ident) / 'meta.json'):
        m = _json(meta) if meta.is_file() else None
        if not isinstance(m, dict): continue
        twin = meta.parent / 'source.txt'
        if meta.parent != sd and not (twin.is_file() and twin.read_bytes() == src.read_bytes()): continue   # another text: not its receipt
        o.update({k: m[k] for k in ('version', 'version_date', 'method') if isinstance(m.get(k), str) and m.get(k)})
        if isinstance(m.get('id'), str) and m['id']: o['id'] = m['id']
        break
    return o, text


def refs_of(d, card):
    """card source key -> bibliography number [n] of REPORT.md (S<n> unless [n] names another document; else a shared identifier)."""
    try:
        import export_data as X
        es = X.bib_entries((d / 'REPORT.md').read_text(encoding='utf-8', errors='replace'))
    except Exception:
        return {}
    ids_of = {n: {X._id(m.group(1), m.group(2)) for m in X.VPID.finditer(t)} for n, t in es}
    srcs = card.get('sources') if isinstance(card, dict) and isinstance(card.get('sources'), dict) else {}
    out = {}
    for k, s in srcs.items():
        mine = set(X._src_ids(s))
        m = re.fullmatch(r'S(\d+)', str(k))
        if m and int(m.group(1)) in ids_of and (not mine or not ids_of[int(m.group(1))] or mine & ids_of[int(m.group(1))]):
            out[k] = int(m.group(1)); continue
        hit = next((n for n, ids in ids_of.items() if mine & ids), None)
        if hit is not None: out[k] = hit
    return out


REASON = {
    'not read': 'no verified passage: the verifier could not read this source',
    'not kept': 'no verified passage: the text the verifier read is not kept in the run folder',
    'ABSENT': 'no verified passage: the verifier found nothing supporting this claim in the {kind} it read',
    'SOURCE-UNAVAILABLE': 'no verified passage: the {kind} the verifier read does not cover this claim',
    'INVALID': 'no verified passage: the verifier\'s fragments failed the mechanical check',
    'UNVERIFIED': 'no verified passage: no verdict for this claim (verifier call failed)',
    'nomatch': 'no verified passage: none of the verifier\'s fragments was found in the kept {kind}',
    'nofrag': 'no verified passage: the verdict carries no fragment',
}


def build(folder, max_chars=None, max_per_claim=None):
    """Run dir -> {'rule', 'max_chars', 'claims': [...], 'summary'}; None when there is no verdicts.json with a `claims` list."""
    d = pathlib.Path(folder)
    ver, card = _json(d / 'verdicts.json'), _json(d / 'card.json')
    if not isinstance(ver, dict) or not isinstance(ver.get('claims'), list): return None
    max_chars = MAX_CHARS if max_chars is None else max_chars
    max_per_claim = MAX_PER_CLAIM if max_per_claim is None else max_per_claim
    card = card if isinstance(card, dict) else {}
    table = card.get('sources') if isinstance(card.get('sources'), dict) else {}
    refs = refs_of(d, card)
    out = []
    for c in ver['claims']:
        if not isinstance(c, dict): continue
        key, status = str(c.get('source') or ''), str(c.get('status') or '').upper()
        o, text = origin(d, key, c.get('source_origin', 'missing'), _ident(table.get(key), key))
        frags = [f for f in (c.get('fragments') or []) if isinstance(f, str)]
        shown, reason, code = [], None, None
        if text is None:
            code = o['kind']; reason = REASON[code]
            note = ' '.join(str(c.get('discrepancy') or '').split())[:200]   # written by verifier.load_sources (gateway refusal or cap), not by a model
            if o['kind'] == 'not read' and note: reason += f' (reading refused: {note})'
        elif status not in PROOF: code = status; reason = REASON.get(status, 'no verified passage: unknown status').format(kind=o['kind'])
        elif not frags: code = 'nofrag'; reason = REASON['nofrag']
        else:
            spans = []
            for f in frags:
                sp = locate(f, text)
                if sp and sp not in spans: spans.append(sp)
            for sp in spans:
                p = passage(text, *sp, max_chars=max_chars)
                prev = next((q for q in shown if q['text'] == p['text']), None)
                if prev: prev['marks'] = sorted(prev['marks'] + [m for m in p['marks'] if m not in prev['marks']])
                elif len(shown) < max_per_claim: shown.append(p)
            if not shown: code = 'nomatch'; reason = REASON['nomatch'].format(kind=o['kind'])
        out.append({'id': c.get('id'), 'claim': c.get('text', ''), 'source': key, 'ref': refs.get(key), 'status': status, 'origin': o,
                    'passages': shown, 'fragments_given': len(frags), **({'reason': reason, 'reason_code': code} if reason else {})})
    n = len(out); w = sum(1 for x in out if x['passages'])
    why = {}
    for x in out:
        if not x['passages']: why[x['reason_code']] = why.get(x['reason_code'], 0) + 1
    return {'rule': 'exact source text: each passage is a substring of DIR/sources/<KEY>/source.txt (whitespace collapsed) located from the '
                    'verifier\'s machine-checked fragments; no passage is ever written by a model',
            'max_chars': max_chars, 'max_per_claim': max_per_claim, 'claims': out,
            'summary': {'claims': n, 'with_passage': w, 'share': round(w / n, 3) if n else None, 'without_passage': why,
                        'by_origin': {k: sum(1 for x in out if x['passages'] and x['origin']['kind'] == k) for k in ('full text', 'record + abstract')}}}


def origin_label(o):
    s = o.get('kind', '')
    if o.get('id'): s = f"{o['id']}, {s}"
    if o.get('version'): s += f" {o['version']}" + (f" ({o['version_date']})" if o.get('version_date') else '')
    return s


def _fence(t):
    n = max([3] + [len(m) + 1 for m in re.findall(r'`+', t)])
    return '`' * n


def _code(t):
    t = ' '.join(str(t).split()); f = '`' * (max([0] + [len(m) for m in re.findall(r'`+', t)]) + 1)
    return f'{f} {t} {f}'


def markdown(doc):
    """Annex in Markdown: one section per bibliography entry, each claim with its passages in inert fenced blocks (never rendered)."""
    lines = ['# Cited Passages', '',
             'Each passage below is copied by tools/passages.py from the source text the verifier read; it is an exact substring of that '
             'text (whitespace collapsed), never written by a model. A claim without one says why.',
             f"Claims with a verified passage: {doc['summary']['with_passage']} of {doc['summary']['claims']}.", '']
    groups = {}
    for c in doc['claims']: groups.setdefault(c['ref'], []).append(c)
    for ref in sorted(groups, key=lambda r: (r is None, r or 0)):
        lines += [f'## [{ref}]' if ref is not None else '## Claims whose source is not in the bibliography', '']
        for c in groups[ref]:
            lines.append(f"- {c['id']} ({c['status']}, source {c['source']}; {origin_label(c['origin'])})")
            lines.append('  Claim (card): ' + _code(c['claim']))
            if not c['passages']: lines.append(f"  {c['reason']}.")
            for p in c['passages']:
                f = _fence(p['text'])
                lines += ['', f'  {f}text', '  ' + p['text'], f'  {f}'] + (['  (cut at max_chars)'] if p['truncated'] else [])
            lines.append('')
    return '\n'.join(lines) + '\n'


def write(folder, out=None):
    doc = build(folder)
    if doc is None: return None
    out = pathlib.Path(out or folder); out.mkdir(parents=True, exist_ok=True)
    (out / 'passages.json').write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'PASSAGES.md').write_text(markdown(doc), encoding='utf-8')
    return doc, [out / 'passages.json', out / 'PASSAGES.md']


def main(argv=None):
    ap = argparse.ArgumentParser(description='verdicts.json + kept source texts -> passages.json and PASSAGES.md (exact cited passages), offline.')
    ap.add_argument('run_dir'); ap.add_argument('--out'); ap.add_argument('--json', action='store_true'); a = ap.parse_args(argv)
    r = write(a.run_dir, a.out)
    if r is None: print(f'no verdicts.json with claims in {a.run_dir}', file=sys.stderr); return 2
    doc, files = r
    for f in files: print(f.resolve())
    s = doc['summary']; print(json.dumps(s, ensure_ascii=False) if a.json else f"{s['with_passage']}/{s['claims']} claims with a verified passage")
    return 0


if __name__ == '__main__':
    sys.exit(main())
