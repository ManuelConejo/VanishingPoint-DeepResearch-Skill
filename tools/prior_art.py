#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prior-art answer of a run (optional "Prior art?" mode, never by default). Standard library, offline, no model.
The question is an idea, a method or a tool described by the user, and a date T. The run uses the same gateway and the same verifier as
a standard run; this tool only turns their records into a short, fixed answer:
  prior_art.json (written at framing): {"idea": "...", "T": "YYYY-MM-DD" (optional, else the journal's), "elements": [{"id": "E1", "text": "..."}]}
    = the idea cut into its essential elements (each one a feature a prior document must disclose);
  card.json: one claim per (source, element) that a searcher read as disclosed, with "element": "E<k>" added to the claim (format of
    SKILL.md section 6 otherwise); card.sources may carry "year";
  verdicts.json: tools/verifier.py, unchanged (an element counts as disclosed only when its claim is FOUND);
  state/journal.jsonl: the gateway journal (engines, queries, counts = the denominator of the answer).
Answer (decided by code, never by a model):
  EXISTS     one source dated before T discloses every element, each claim FOUND;
  PARTIALLY  at least one element is disclosed (FOUND) but no single source discloses all of them;
  NOT FOUND  no element is disclosed by a verified claim; the answer then states what was searched: engines, queries, records identified,
             distinct, read, removed by the date barrier, and the kinds of sources not searched (patents when no patent engine is wired).
  PENDING    verdicts.json missing: no answer before verification.
DISTORTED, SOURCE-UNAVAILABLE and UNVERIFIED never count as disclosed; when counting the unverified ones as disclosed would change the
answer, the answer says so. Closest prior art = most elements disclosed, then most elements claimed, then earliest year (config
prior_art.closest entries). "What differs" = the elements each closest source does not disclose, with the verifier's discrepancy.
Output: DIR/PRIOR-ART.md (fixed short template, below) and DIR/prior_art_result.json; the first line of PRIOR-ART.md carries the
fingerprint of its inputs, which validate_card.py --prior-art compares with the files (a stale answer is refused).
Usage: prior_art.py RUN_DIR [--json]     Exit: 0 written; 1 prior_art.json missing or invalid (problems printed); 2 not a directory.
Import: decide(dir) -> dict ; render(data) -> str ; problems(dir) -> [str] (the checks used by validate_card.py --prior-art)."""
import argparse, hashlib, json, pathlib, re, sys

P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P))
import prisma   # noqa: E402  (journal, search_summary, card_ids)

ORDER = ['FOUND', 'DISTORTED', 'SOURCE-UNAVAILABLE', 'UNVERIFIED', 'ABSENT', 'INVALID']   # best first, for one (source, element)
UNSURE = ('SOURCE-UNAVAILABLE', 'UNVERIFIED')
ANSWERS = {'EXISTS': 'Exists', 'PARTIALLY': 'Partially', 'NOT FOUND': 'Not found', 'PENDING': 'Pending verification'}
INPUTS = ('prior_art.json', 'card.json', 'verdicts.json', 'state/journal.jsonl')
FP = re.compile(r'^<!-- prior_art\.py inputs sha256:([0-9a-f]{64}) answer:([A-Z ]+) -->')
EID = re.compile(r'^E\d{1,3}$')
PATENT = re.compile(r'patent', re.I)


def _cfg():
    try: c = json.loads((P / 'config.json').read_text(encoding='utf-8')).get('prior_art') or {}
    except (OSError, ValueError): c = {}
    return {'elements_max': int(c.get('elements_max', 8)), 'closest': int(c.get('closest', 3)), 'queries_max': int(c.get('queries_max', 100)),
            'claim_chars': int(c.get('claim_chars', 200)), 'idea_chars': int(c.get('idea_chars', 90))}


CFG = _cfg()


def _json(p):
    try: return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError): return None


def fingerprint(d):
    h = hashlib.sha256()
    for f in INPUTS:
        p = pathlib.Path(d) / f
        h.update(f.encode() + b'\0' + (hashlib.sha256(p.read_bytes()).hexdigest().encode() if p.is_file() else b'-') + b'\0')
    return h.hexdigest()


def spec_problems(spec):
    pb = []
    if not isinstance(spec, dict): return ['PA1 prior_art.json: missing or unreadable JSON']
    if not str(spec.get('idea') or '').strip(): pb.append('PA1 prior_art.json: empty "idea"')
    el = spec.get('elements')
    if not isinstance(el, list) or not el: pb.append('PA1 prior_art.json: "elements" must be a non-empty list'); return pb
    if len(el) > CFG['elements_max']: pb.append(f'PA1 prior_art.json: {len(el)} elements, at most {CFG["elements_max"]} (prior_art.elements_max)')
    ids = [e.get('id') if isinstance(e, dict) else None for e in el]
    for e in el:
        if not isinstance(e, dict) or not EID.match(str(e.get('id') or '')) or not str(e.get('text') or '').strip():
            pb.append(f'PA1 prior_art.json: element {e!r} needs "id" E<k> and a non-empty "text"')
    if len(set(ids)) != len(ids): pb.append('PA1 prior_art.json: duplicate element ids')
    if spec.get('T') and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(spec['T'])): pb.append(f'PA1 prior_art.json: T {spec["T"]!r} not YYYY-MM-DD')
    return pb


def _short(s, n):
    s = ' '.join(str(s or '').split())
    return s if len(s) <= n else s[:n].rsplit(' ', 1)[0] + '...'


def decide(d):
    d = pathlib.Path(d)
    spec = _json(d / 'prior_art.json'); card = _json(d / 'card.json'); ver = _json(d / 'verdicts.json')
    card = card if isinstance(card, dict) else {}
    elements = [e['id'] for e in (spec or {}).get('elements') or [] if isinstance(e, dict) and e.get('id')]
    etext = {e['id']: e.get('text') for e in (spec or {}).get('elements') or [] if isinstance(e, dict) and e.get('id')}
    status = {v.get('id'): v for v in (ver or {}).get('claims') or [] if isinstance(v, dict)} if isinstance(ver, dict) else None
    src = card.get('sources') or {}
    per = {}                                                      # key -> element -> (status, claim, verdict)
    for c in card.get('claims') or []:
        if not isinstance(c, dict) or c.get('element') not in etext: continue
        k = (c.get('source') or {}).get('key')
        v = (status or {}).get(c.get('id')) or {}
        st = v.get('status') if status is not None else None
        st = st if st in ORDER else ('UNVERIFIED' if status is not None else None)
        cur = per.setdefault(k, {}).get(c['element'])
        if cur is None or (st in ORDER and (cur[0] not in ORDER or ORDER.index(st) < ORDER.index(cur[0]))):
            per[k][c['element']] = (st, c, v)

    def verdict(optimistic=False):
        ok = lambda st: st == 'FOUND' or (optimistic and st in UNSURE)
        full = [k for k, m in per.items() if all(e in m and ok(m[e][0]) for e in elements)]
        anyel = any(ok(m[e][0]) for m in per.values() for e in m)
        return ('EXISTS' if full else 'PARTIALLY' if anyel else 'NOT FOUND'), full

    T = (spec or {}).get('T') or (prisma.search_summary(d)['T'] or [''])[-1] or str(card.get('T') or '')
    data = {'dir': str(d), 'idea': (spec or {}).get('idea'), 'T': T, 'elements': [{'id': e, 'text': etext[e]} for e in elements]}
    if status is None:
        data.update(answer='PENDING', exists_in=[], could_be=None)
    else:
        a, full = verdict(); o, _ = verdict(True)
        data.update(answer=a, exists_in=sorted(full, key=_keynum), could_be=o if o != a else None)
    disclosed = {e: sorted((k for k, m in per.items() if e in m and m[e][0] == 'FOUND'), key=_keynum) for e in elements}
    data['coverage'] = [{'element': e, 'disclosed_by': disclosed[e],
                         'other': sorted(((k, m[e][0]) for k, m in per.items() if e in m and m[e][0] != 'FOUND'), key=lambda x: _keynum(x[0]))} for e in elements]
    data['novel_elements'] = [e for e in elements if not disclosed[e]]

    def rank(k):
        m = per[k]; y = str((src.get(k) or {}).get('year') or '9999') if isinstance(src.get(k), dict) else '9999'
        return (-sum(m[e][0] == 'FOUND' for e in m), -len(m), y, _keynum(k))
    closest = []
    for k in sorted(per, key=rank)[:CFG['closest']]:
        m = per[k]; s = src.get(k) if isinstance(src.get(k), dict) else {}
        ident = next((f'{f}:{v}' for f, v in s.items() if f not in ('title', 'year', 'authors', 'note') and isinstance(v, str)), '')
        closest.append({'key': k, 'ref': _ref(k), 'title': s.get('title'), 'year': s.get('year'), 'id': ident,
                        'elements': [{'element': e, 'status': m[e][0] if e in m else 'not claimed', 'claim': m[e][1].get('id') if e in m else None,
                                      'text': _short(m[e][1].get('text'), CFG['claim_chars']) if e in m else None,
                                      'discrepancy': _short((m[e][2] or {}).get('discrepancy'), CFG['claim_chars']) if e in m else None,
                                      'fragment': _short(((m[e][2] or {}).get('fragments') or [None])[0], CFG['claim_chars']) if e in m else None} for e in elements]})
    data['closest'] = closest
    counts = {}
    for k, m in per.items():
        for e, (st, c, v) in m.items(): counts[st or 'none'] = counts.get(st or 'none', 0) + 1
    data['claims'] = {'checked': sum(1 for c in card.get('claims') or [] if isinstance(c, dict) and c.get('element') in etext), 'best_per_source_element': counts,
                      'unverified': sorted([c.get('id') for c in card.get('claims') or [] if isinstance(c, dict) and ((status or {}).get(c.get('id')) or {}).get('status') in UNSURE], key=_keynum)}
    data['searched'] = searched(d)
    data['fingerprint'] = fingerprint(d)
    return data


def _keynum(k):
    m = re.search(r'\d+', str(k)); return (int(m.group(0)) if m else 10 ** 6, str(k))


def _ref(k):
    m = re.fullmatch(r'S(\d+)', str(k or '')); return f'[{m.group(1)}]' if m else str(k)


def searched(d):
    """What was searched, from the journal only: engines and their kinds, queries, records (the denominator)."""
    s = prisma.search_summary(d)
    try:
        import sources as _reg
        code = set(_reg.CODE_ENGINES.values()) | set(_reg.CODE_ENGINES); wired = set(_reg.ENGINES) | code
    except Exception:
        code, wired = set(), set()
    patents_wired = sorted(e for e in wired if PATENT.search(e))
    used = set(s['per_source'])
    kinds = {'papers and records': sorted(e for e in used if e not in code and not PATENT.search(e)),
             'code': sorted(e for e in used if e in code), 'patents': sorted(e for e in used if PATENT.search(e))}
    reads = sum(1 for e in prisma.journal(d) if e.get('call') == 'read')
    return {**s, 'kinds': kinds, 'patent_engines_wired': patents_wired, 'reads': reads}


def render(data):
    a = data['answer']; s = data['searched']; t = s['totals']
    L = [f'<!-- prior_art.py inputs sha256:{data["fingerprint"]} answer:{a} -->',
         f'# Prior art? {_short(data.get("idea"), CFG["idea_chars"])}', '',
         f'Date T: {data.get("T") or "not recorded"}. Mode: prior art (optional). Answer decided by code from the verified claims (tools/prior_art.py).', '',
         '## Answer', '']
    els = [e['id'] for e in data['elements']]
    if a == 'EXISTS':
        L.append(f'**{ANSWERS[a]}** as of {data["T"]}: ' + ' and '.join(_ref(k) for k in data['exists_in']) + f' disclose{"s" if len(data["exists_in"]) == 1 else ""} every element ({", ".join(els)}), each claim verified FOUND.')
    elif a == 'PARTIALLY':
        cov = [e for e in els if e not in data['novel_elements']]
        L.append(f'**{ANSWERS[a]}** as of {data["T"]}: element(s) {", ".join(cov)} are disclosed (verified FOUND), but no single source discloses all of them; '
                 + (f'element(s) {", ".join(data["novel_elements"])} are disclosed by no source read.' if data['novel_elements'] else 'each element is disclosed somewhere, never all in one source (a combination, not an anticipation).'))
    elif a == 'NOT FOUND':
        L.append(f'**{ANSWERS[a]}** as of {data["T"]}: no element of the idea is disclosed by a verified claim among the {t["distinct_ids"]} distinct records '
                 f'returned by {t["search_calls"] + t["chain_calls"]} searches and the {s["reads"]} documents read (what was searched: below). Not found is not proof of absence.')
    else:
        L.append(f'**{ANSWERS[a]}**: verdicts.json is missing; no answer before the downstream verification (SKILL.md section 7).')
    if data.get('could_be'):
        L.append(f'Could be **{ANSWERS[data["could_be"]]}** if the unverified claim(s) {", ".join(data["claims"]["unverified"])} were confirmed (SOURCE-UNAVAILABLE or UNVERIFIED count as not disclosed).')
    L += ['', '## The idea, element by element', '', '| Element | Text | Disclosed by (FOUND) | Claimed, not verified as disclosed |', '|---|---|---|---|']
    for e, c in zip(data['elements'], data['coverage']):
        L.append(f'| {e["id"]} | {_cell(e["text"])} | {", ".join(_ref(k) for k in c["disclosed_by"]) or "none"} | {", ".join(f"{_ref(k)} {st}" for k, st in c["other"]) or "-"} |')
    L += ['', '## Closest prior art', '']
    if not data['closest']: L.append('None: no source read was claimed to disclose any element.')
    for n, c in enumerate(data['closest'], 1):
        L.append(f'{n}. {c["ref"]} {_short(c.get("title") or "", CFG["claim_chars"])}' + (f' ({c["year"]})' if c.get('year') else '') + (f', `{c["id"]}`' if c.get('id') else '')
                 + f': discloses {sum(x["status"] == "FOUND" for x in c["elements"])} of {len(c["elements"])} elements.')
        for x in c['elements']:
            if x['status'] == 'FOUND': L.append(f'   - {x["element"]} FOUND ({x["claim"]}): "{x["fragment"] or x["text"]}"')
    L += ['', '## What differs', '']
    if data['novel_elements']: L.append(f'Disclosed by no source read: {", ".join(f"{e} ({_short(next(x["text"] for x in data["elements"] if x["id"] == e), CFG["claim_chars"])})" for e in data["novel_elements"])}.')
    for c in data['closest']:
        miss = [x for x in c['elements'] if x['status'] != 'FOUND']
        if not miss: L.append(f'- {c["ref"]}: nothing; it discloses every element.'); continue
        L.append(f'- {c["ref"]}: ' + '; '.join(f'{x["element"]} {x["status"]}' + (f' ({x["discrepancy"]})' if x.get('discrepancy') else '') for x in miss) + '.')
    if not data['closest'] and not data['novel_elements']: L.append('Nothing to compare.')
    L += ['', '## What was searched', '']
    if not s['journal']: L.append('Not recorded: no state/journal.jsonl (injected mode or no search).')
    else:
        L.append(f'Denominator: {t["search_calls"]} searches and {t["chain_calls"]} citation-chaining calls returned {t["records"]} records ({t["distinct_ids"]} distinct identifiers); '
                 f'{t["date_barrier"]} more were removed by the date barrier (dated on or after T); {s["reads"]} documents were read; {t["errors"]} calls ended in error.')
        L.append('Engines: ' + '; '.join(f'{k} ({v["calls"]} calls, {v["records"]} records)' for k, v in sorted(s['per_source'].items())) + '.')
        k = s['kinds']
        L.append('Kinds of sources: papers and records: ' + (', '.join(k['papers and records']) or 'none') + '; code: ' + (', '.join(k['code']) or 'not searched')
                 + '; patents: ' + (', '.join(k['patents']) if k['patents'] else ('not searched (no patent engine was called)' if s['patent_engines_wired'] else 'not searched: no patent source is wired in the gateway (tools/sources/)')) + '.')
        q = s['queries']
        L += ['', f'Queries ({len(q)}):', '']
        for x in q[:CFG['queries_max']]:
            L.append(f'- `{x["command"]}` "{_cell(x["query"])}": {x["records"]} records' + (f', {x["date_barrier"]} after T' if x['date_barrier'] else '') + (f', error' if x.get('error') else ''))
        if len(q) > CFG['queries_max']: L.append(f'- and {len(q) - CFG["queries_max"]} more (state/journal.jsonl)')
    cl = data['claims']
    L += ['', '## Verification', '', f'{cl["checked"]} element claims checked by the verifier (tools/verifier.py); best status per source and element: '
          + (', '.join(f'{k} {v}' for k, v in sorted(cl['best_per_source_element'].items())) or 'none') + '. Only FOUND counts as disclosed; '
          + (f'unverified: {", ".join(cl["unverified"])}.' if cl['unverified'] else 'no claim left unverified.'), '']
    return '\n'.join(L) + '\n'


def _cell(s): return ' '.join(str(s or '').split()).replace('|', '\\|')


def problems(d):
    """Prior-art checks for validate_card.py --prior-art: PA1 prior_art.json; PA2 element claims; PA3 PRIOR-ART.md current and consistent;
    PA4 a NOT FOUND answer has a recorded search."""
    d = pathlib.Path(d); spec = _json(d / 'prior_art.json'); pb = spec_problems(spec)
    if pb: return pb
    card = _json(d / 'card.json'); els = {e['id'] for e in spec['elements']}
    for c in (card or {}).get('claims') or [] if isinstance(card, dict) else []:
        if c.get('element') not in els: pb.append(f'PA2 claim {c.get("id")}: "element" {c.get("element")!r} not among {sorted(els)}')
    p = d / 'PRIOR-ART.md'
    if not p.is_file(): pb.append('PA3 PRIOR-ART.md missing: run python3 -I tools/prior_art.py <dir>'); return pb
    m = FP.match(p.read_text(encoding='utf-8', errors='replace').split('\n', 1)[0])
    if not m: pb.append('PA3 PRIOR-ART.md: not written by tools/prior_art.py (fingerprint line missing)'); return pb
    if m.group(1) != fingerprint(d): pb.append('PA3 PRIOR-ART.md stale: prior_art.json, card.json, verdicts.json or the journal changed since; rerun tools/prior_art.py')
    data = decide(d)
    if m.group(2).strip() != data['answer']: pb.append(f'PA3 PRIOR-ART.md answer {m.group(2).strip()!r} differs from the answer of the files {data["answer"]!r}')
    if data['answer'] == 'PENDING': pb.append('PA3 answer pending: verdicts.json missing (tools/verifier.py verify)')
    if data['answer'] == 'NOT FOUND' and not (data['searched']['totals']['search_calls'] + data['searched']['totals']['chain_calls']):
        pb.append('PA4 NOT FOUND without any search recorded in state/journal.jsonl')
    return pb


def write(d):
    d = pathlib.Path(d); data = decide(d)
    (d / 'PRIOR-ART.md').write_text(render(data), encoding='utf-8')
    (d / 'prior_art_result.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    return data, [d / 'PRIOR-ART.md', d / 'prior_art_result.json']


def main(argv=None):
    ap = argparse.ArgumentParser(description='Prior-art answer (exists / partially / not found) from the verified element claims of a run. Offline, no model.')
    ap.add_argument('run_dir'); ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    d = pathlib.Path(a.run_dir)
    if not d.is_dir(): print(f'not a directory: {a.run_dir}', file=sys.stderr); return 2
    pb = spec_problems(_json(d / 'prior_art.json'))
    if pb: print('\n'.join(pb)); return 1
    data, files = write(d)
    if a.json: print(json.dumps(data, ensure_ascii=False, indent=1))
    print(f'answer: {data["answer"]}' + (f' (could be {data["could_be"]} if the unverified claims were confirmed)' if data.get('could_be') else ''))
    for f in files: print(f.resolve())
    return 0


if __name__ == '__main__':
    sys.exit(main())
