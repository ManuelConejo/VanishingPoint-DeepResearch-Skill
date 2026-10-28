#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Follow-up questions at the end of a run (optional, never by default). Standard library, offline, no model: fixed templates filled
from the run's own files, never a generated sentence.
Families, in this order of priority (one question per family in turn, then again, up to `followups.max` of tools/config.json):
  1 verification: claims DISTORTED in verdicts.json; claims found ABSENT or INVALID (still in verdicts.json, or removed and named with
    their id in result.json `verification.rule` or in the methodology appendix of REPORT.md);
  2 unavailable: claims SOURCE-UNAVAILABLE; sources the verifier could not obtain (state/verifier.json `per_source` origin "missing");
    identifiers the searchers could not read (gateway journal: every read failed or refused);
  3 angle: angles of scope.md ("## Angles", numbered) whose searchers' files (searches/<n>.md naming the angle in their header) hold no
    identifier cited in card.json; empty angles the report states ("Empty angles: ...", "no source seen on ...");
  4 contradiction: discrepancies of verdicts.json that name a conflict (contradict, conflict, opposite, inconsistent, disagree) and the
    elements tools/contradictor.py marked "false detected" (contradictor.json).
Fewer than `followups.min` derivable questions: the file says so and lists only those; nothing is invented to reach the count.
Outputs: DIR/FOLLOWUPS.md and DIR/followups.json ({"questions": [{"family", "text", "refs", "from"}], ...}); export_report.py --followups
shows them in REPORT.html.
Usage: followups.py RUN_DIR [--out DIR] [--json]     Exit: 0 written; 2 not a directory.
Import: build(dir) -> dict ; candidates(dir) -> {family: [question]} ; markdown(data) -> str."""
import argparse, json, pathlib, re, sys

P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P))
import prisma   # noqa: E402  (journal, norm_id, card_ids)

FAMILIES = ('verification', 'unavailable', 'angle', 'contradiction')
TEMPLATES = {
    'distorted': 'What do sources other than {ref} report on "{claim}"? The verifier found that {ref} does not support it as written: {why}.',
    'absent': 'Which source, dated before {T}, supports "{claim}"? The claim ({cid}) was {fate} because {ref} does not state it.',
    'unavailable_claim': 'Does the full text of {ref} ({title}) support "{claim}"? The verifier could not read a text that settles it: {why}.',
    'unavailable_source': 'Does the full text of {ref} ({title}) support the claims the report draws from it? The verifier could not obtain its text.',
    'unread': 'What does {ident} say on the question? The searchers could not retrieve it through the gateway during the run.',
    'angle': 'What do sources dated before {T} say on angle {k} of the scope, "{angle}"? No source cited in the report comes from it.',
    'empty': 'Is there a source, dated before {T}, on {what}? The report states that none was seen.',
    'conflict': 'Which reading holds for "{claim}"? The verifier noted a conflict with {ref}: {why}.',
    'contradictor': 'Is "{claim}" right? A contradictor of another model family ({family}) disputed it: {why}.',
}
CONFLICT = re.compile(r'\b(contradict\w*|conflict\w*|opposite|inconsistent|disagree\w*)\b', re.I)
REMOVAL = re.compile(r'\b(ABSENT|INVALID|removed|removal\w*)\b', re.I)
REMOVED_ID = re.compile(r'(?:\[(\d{1,3})\]`?\s*/\s*`?)?\bA(\d{1,4})\b(?:`)?(?:\s*\(([^()]{3,240})\))?')
EMPTY = (re.compile(r'\bEmpty angles?(?:\s*\([^)]*\))?\s*:\s*([^\n]+?)(?:\.\s|\.$|$)', re.I),
         re.compile(r'\bno (?:source|study|studies|document) (?:was )?(?:seen|found) (?:on|about|for)\s+([^.;\n]+)', re.I))


def _cfg():
    try: c = json.loads((P / 'config.json').read_text(encoding='utf-8')).get('followups') or {}
    except (OSError, ValueError): c = {}
    return {'min': int(c.get('min', 3)), 'max': int(c.get('max', 5)), 'claim_chars': int(c.get('claim_chars', 160)),
            'why_chars': int(c.get('why_chars', 200)), 'angle_chars': int(c.get('angle_chars', 120)), 'templates': {**TEMPLATES, **(c.get('templates') or {})}}


CFG = _cfg()


def _short(s, n):
    s = ' '.join(str(s or '').split()).strip().rstrip('.')
    s = s.replace('"', "'")
    return s if len(s) <= n else s[:n].rsplit(' ', 1)[0] + '...'


def _json(p):
    try: return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError): return None


def _text(p):
    try: return pathlib.Path(p).read_text(encoding='utf-8', errors='replace')
    except OSError: return ''


def _section(md, title):
    m = re.search(r'^## +' + re.escape(title) + r'\s*$(.*?)(?=^## |\Z)', md, re.M | re.S)
    return m.group(1) if m else ''


def _ref(key):
    m = re.fullmatch(r'S(\d+)', str(key or ''))
    return f'[{m.group(1)}]' if m else (str(key) if key else 'its source')


def _q(fam, tpl, refs, frm, **kw):
    return {'family': fam, 'text': CFG['templates'][tpl].format(**kw), 'refs': refs, 'from': frm}


def candidates(d):
    d = pathlib.Path(d)
    card = _json(d / 'card.json'); card = card if isinstance(card, dict) else {}
    ver = _json(d / 'verdicts.json'); ver = ver if isinstance(ver, dict) else {}
    res = _json(d / 'result.json'); res = res if isinstance(res, dict) else {}
    vj = _json(d / 'state' / 'verifier.json'); vj = vj if isinstance(vj, dict) else {}
    report = _text(d / 'REPORT.md')
    J = prisma.journal(d)
    T = (sorted({str(e.get('T')) for e in J if e.get('T')}) or [str(card.get('T') or '')])[-1] or 'T'
    claims = {c.get('id'): c for c in card.get('claims') or [] if isinstance(c, dict)}
    src = card.get('sources') or {}
    title = lambda k: _short((src.get(k) or {}).get('title') or k, CFG['claim_chars'] // 2) if isinstance(src.get(k), dict) else str(k)
    V = [v for v in ver.get('claims') or [] if isinstance(v, dict)]
    key_of = lambda v: (v.get('source') if isinstance(v.get('source'), str) else (v.get('source') or {}).get('key')) or ((claims.get(v.get('id')) or {}).get('source') or {}).get('key')
    ctext = lambda v: _short(v.get('text') or (claims.get(v.get('id')) or {}).get('text'), CFG['claim_chars'])
    out = {f: [] for f in FAMILIES}
    # 1 verification
    for v in V:
        st, k = v.get('status'), key_of(v)
        if st == 'DISTORTED':
            out['verification'].append(_q('verification', 'distorted', [v.get('id'), _ref(k)], 'verdicts.json DISTORTED', ref=_ref(k), claim=ctext(v), why=_short(v.get('discrepancy'), CFG['why_chars']) or 'no discrepancy recorded'))
        elif st in ('ABSENT', 'INVALID'):
            out['verification'].append(_q('verification', 'absent', [v.get('id'), _ref(k)], f'verdicts.json {st}', T=T, claim=ctext(v), cid=v.get('id'), fate=f'found {st}', ref=_ref(k)))
    present = {v.get('id') for v in V} | set(claims)
    removal_text = str((res.get('verification') or {}).get('rule') or '') + '\n' + _section(report, 'Methodology Appendix')
    seen_removed = set()
    for sent in re.split(r'(?<=[.;])\s+|\n', removal_text):
        if not REMOVAL.search(sent): continue
        for m in REMOVED_ID.finditer(sent):
            cid = f'A{m.group(2)}'
            if cid in present or cid in seen_removed: continue
            desc = re.sub(r'^\s*(ABSENT|INVALID)\s*[,;:]?\s*', '', m.group(3) or '', flags=re.I)
            if not desc: continue                      # an id without what it said: nothing to ask about
            seen_removed.add(cid)
            out['verification'].append(_q('verification', 'absent', [cid] + ([f'[{m.group(1)}]'] if m.group(1) else []), 'removal recorded in result.json / methodology appendix',
                                          T=T, claim=_short(desc, CFG['claim_chars']), cid=cid, fate='removed after verification', ref=f'[{m.group(1)}]' if m.group(1) else 'its cited source'))
    # 2 unavailable
    keys_un = []
    for v in V:
        if v.get('status') == 'SOURCE-UNAVAILABLE':
            k = key_of(v)
            if k in keys_un: continue                 # one question per source
            keys_un.append(k)
            out['unavailable'].append(_q('unavailable', 'unavailable_claim', [v.get('id'), _ref(k)], 'verdicts.json SOURCE-UNAVAILABLE', ref=_ref(k), title=title(k), claim=ctext(v),
                                         why=_short(v.get('discrepancy'), CFG['why_chars']) or 'no reason recorded'))
    for k, ps in sorted((vj.get('per_source') or {}).items(), key=lambda x: int(re.sub(r'\D', '', x[0]) or 0)):
        if isinstance(ps, dict) and ps.get('origin') == 'missing' and k not in keys_un:
            keys_un.append(k); out['unavailable'].append(_q('unavailable', 'unavailable_source', [_ref(k)], 'state/verifier.json origin missing', ref=_ref(k), title=title(k)))
    reads = {}
    for e in J:
        if e.get('call') == 'read' and e.get('query'):
            i = prisma.norm_id(e['query']); reads[i] = reads.get(i, False) or (not e.get('error') and any(x for x in (e.get('ids') or [])))
    for i in sorted(i for i, ok in reads.items() if not ok):
        out['unavailable'].append(_q('unavailable', 'unread', [i], 'gateway journal: read failed or refused', ident=i))
    # 3 angles
    cited = set().union(*prisma.card_ids(card).values()) if src else set()
    scope = _text(d / 'scope.md')
    m = re.search(r'^#{1,3}\s*Angles?\b[^\n]*\n(.*?)(?=^#{1,3}\s|\Z)', scope, re.M | re.S)
    angles = {int(a): t for a, t in re.findall(r'^\s*(\d{1,2})[.)]\s+(.+)$', m.group(1), re.M)} if m else {}
    files = {}
    for p in sorted((d / 'searches').glob('*.md')) if (d / 'searches').is_dir() else []:
        t = _text(p); head = '\n'.join(t.splitlines()[:3])
        for g in re.finditer(r'\bangles?\s*:?\s*(\d{1,2}(?:\s*(?:,|and|&|\+)\s*\d{1,2})*)', head, re.I):
            for a in re.findall(r'\d+', g.group(1)): files.setdefault(int(a), []).append(t)
    if angles and files:
        for k, a in sorted(angles.items()):
            hit = any(i in cited for t in files.get(k, []) for i in _ids(t))
            if not hit:
                out['angle'].append(_q('angle', 'angle', [f'angle {k}'], 'scope.md angle without a cited source in its searches/ files', T=T, k=k,
                                       angle=_short(re.split(r'(?<=[a-z)\]"])\.\s|\s+Calls?\s*~|\s+Engines?:', a, 1)[0], CFG['angle_chars'])))
    for rx in EMPTY:
        for mm in rx.finditer(_section(report, 'Limitations & Caveats') + '\n' + _section(report, 'Executive Summary')):
            for part in re.split(r';\s*', mm.group(1)):
                part = re.sub(r'^(?:no (?:(?:source|study|studies|document)s? (?:seen |found )?(?:on|about|for)\s+)?)', '', part.strip(), flags=re.I)
                if len(part) > 3:
                    out['angle'].append(_q('angle', 'empty', [], 'REPORT.md: empty angle stated', T=T, what=_short(part, CFG['angle_chars'])))
    # 4 contradictions
    for v in V:
        if v.get('status') in ('DISTORTED', 'ABSENT', 'INVALID') and CONFLICT.search(str(v.get('discrepancy') or '')):
            k = key_of(v)
            out['contradiction'].append(_q('contradiction', 'conflict', [v.get('id'), _ref(k)], f'verdicts.json {v.get("status")}: conflict named in the discrepancy', claim=ctext(v),
                                           ref=_ref(k), why=_short(v.get('discrepancy'), CFG['why_chars'])))
    cj = _json(d / 'contradictor.json')
    for e in (cj or {}).get('elements') or [] if isinstance(cj, dict) else []:
        if isinstance(e, dict) and e.get('status') == 'false detected':
            out['contradiction'].append(_q('contradiction', 'contradictor', [str(e.get('position') or '')], 'contradictor.json false detected',
                                           claim=_short(e.get('quote'), CFG['claim_chars']), family=e.get('family'), why=_short(e.get('why'), CFG['why_chars'])))
    for f in out:                                      # the same sentence twice is one question; removals before corrections;
        seen, keep = set(), []                         # within a family, one question per reference before a second one on the same reference
        for q in sorted(out[f], key=lambda q: 0 if re.search(r'ABSENT|INVALID|removal', q['from']) else 1):
            if q['text'] not in seen: seen.add(q['text']); keep.append(q)
        first, again, refs = [], [], set()
        for q in keep:
            r = q['refs'][-1] if q['refs'] else None
            (again if r and r in refs else first).append(q); refs.add(r)
        out[f] = first + again
    return out


def _ids(text):
    for p in prisma._prefixes():
        for m in re.finditer(r'(?<![\w/])' + re.escape(p) + r':\s?([^\s,;|()\[\]`"\']+)', text, re.I):
            yield prisma.norm_id(f'{p}:{m.group(1)}')
    for m in re.finditer(r'pmid:\s?\d+(?:\s*,\s*\d{5,9})+', text, re.I):        # "pmid:1, 2, 3" lists
        for n in re.findall(r'\d{5,9}', m.group(0)): yield f'pmid:{n}'


def build(d):
    c = candidates(d)
    picked, idx, used = [], {f: 0 for f in FAMILIES}, set()        # one question per claim id across families (a DISTORTED that names a conflict)
    while len(picked) < CFG['max'] and any(idx[f] < len(c[f]) for f in FAMILIES):
        for f in FAMILIES:
            while idx[f] < len(c[f]) and c[f][idx[f]]['refs'] and c[f][idx[f]]['refs'][0] in used: idx[f] += 1
            if len(picked) >= CFG['max']: break
            if idx[f] < len(c[f]):
                q = c[f][idx[f]]; picked.append(q); idx[f] += 1
                if q['refs'] and re.fullmatch(r'A\d+', str(q['refs'][0])): used.add(q['refs'][0])
    return {'dir': str(d), 'questions': picked, 'available': {f: len(c[f]) for f in FAMILIES}, 'min': CFG['min'], 'max': CFG['max'],
            'short': len(picked) < CFG['min'], 'rule': 'templates filled from the run files (tools/followups.py), no model'}


def markdown(data):
    L = ['# Follow-up questions', '', 'Derived mechanically from this run (claims the verifier did not confirm, sources that could not be read, angles of the scope '
         'without a cited source, conflicts the verifier noted), by fixed templates (tools/followups.py); no model wrote them.', '']
    for k, q in enumerate(data['questions'], 1):
        L.append(f'{k}. {q["text"]} _({q["family"]}; from {q["from"]})_')
    if not data['questions']: L.append('No follow-up question is derivable from this run: none of the four families (claims not confirmed, sources not read, angles without a cited source, conflicts noted) has an entry in its files.')
    elif data['short']: L += ['', f'Only {len(data["questions"])} question(s) derivable from the run ({data["min"]} to {data["max"]} sought); none was invented to reach the count.']
    return '\n'.join(L) + '\n'


def write(d, out=None):
    d = pathlib.Path(d); o = pathlib.Path(out) if out else d; o.mkdir(parents=True, exist_ok=True)
    data = build(d)
    (o / 'FOLLOWUPS.md').write_text(markdown(data), encoding='utf-8')
    (o / 'followups.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    return data, [o / 'FOLLOWUPS.md', o / 'followups.json']


def main(argv=None):
    ap = argparse.ArgumentParser(description='Follow-up questions of a run, from fixed templates filled with its own records. Offline, no model.')
    ap.add_argument('run_dir'); ap.add_argument('--out'); ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    if not pathlib.Path(a.run_dir).is_dir(): print(f'not a directory: {a.run_dir}', file=sys.stderr); return 2
    data, files = write(a.run_dir, a.out)
    if a.json: print(json.dumps(data, ensure_ascii=False, indent=1))
    for f in files: print(f.resolve())
    return 0


if __name__ == '__main__':
    sys.exit(main())
