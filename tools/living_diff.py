#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Living review: mechanical comparison of two runs of the same question at T1 < T2 (SKILL.md section 8, "Updating a previous run").
Offline, no model, standard library. Never edits either run: it writes UPDATE.md and update.json only.
Usage: living_diff.py OLD_DIR NEW_DIR [--out FILE]     FILE = path of UPDATE.md (default NEW_DIR/UPDATE.md); update.json is written beside it.
Read in each dir: card.json and REPORT.md (required), result.json, verdicts.json, run.json, scope.md, sources/<key>/source.txt header,
state/journal.jsonl (all optional). T of a run: run.json > journal > scope.md / REPORT.md "T = YYYY-MM-DD".
Source identity: every identifier known for a bibliography entry [n] (its line, card.sources S<n>, the `id:`/`doi:` header of its source.txt,
result.json), normalised (doi lowercased without resolver prefix, doi 10.48550/arxiv.X -> arxiv:X, arxiv without version, pmid digits,
PMC/NCT/CELEX upper, the others lowercased); two entries are one source when they share one identifier, else when their normalised
title + year are equal. Date of a new source (source.txt `date:` > year): on or after T1 = new evidence (it could not be served at T1);
before T1 = older, then "seen at T1 but not kept" when the old journal lists one of its identifiers, else "not found at T1"; a year equal
to the year of T1 without a full date = undetermined. Findings: `### Finding n — title` matched across runs by title similarity
(>= MATCH_MIN, greedy best pairs); verdict = the line starting with "Verdict" in the finding, its words = VERDICT_WORDS found in it, in order.
Also: the first sentence of each Executive Summary and the one-line summary (last paragraph of Methodology Appendix); verification counts
per status; DISTORTED claims and retraction/erratum/concern mentions newly attached to a source.
UPDATE.md holds a prose paragraph ready to paste under `### What changed since T1` in the new report's Methodology Appendix (its [n] are
the new report's numbers; dropped sources are named by title and year, never by [n]), then the details. Exit: 0 written; 2 a dir lacks
card.json or REPORT.md. Import: compare(old, new) -> dict; render(diff) -> str."""
import argparse, difflib, json, pathlib, re, sys

MATCH_MIN = 0.5                                       # title similarity under which two findings are not the same finding
VERDICT_WORDS = ('established', 'probable', 'possible', 'open', 'unlikely', 'refuted', 'NO-GO', 'GO', 'WATCH', 'Y side', 'X side', 'consequence')
FLAG = re.compile(r'retract\w*|erratum|errata|expression of concern', re.I)
STATUS_ORDER = ('FOUND', 'DISTORTED', 'ABSENT', 'SOURCE-UNAVAILABLE', 'INVALID', 'UNVERIFIED')
PREFIXES = ('doi', 'pmid', 'pmcid', 'arxiv', 'celex', 'ecli', 'ja', 'hal', 'thesesfr', 'nct', 'dblp', 'econbiz', 'osv', 'openreview', 'zenodo', 'hfmodel', 'hfdataset', 'rfc', 'pep', 'w3c', 'acl', 'pmlr', 'cvf', 'code')
ID_RE = re.compile(r'\b(' + '|'.join(PREFIXES) + r'):\s?([^\s,;()\[\]]+)', re.I)
DATE_RE = re.compile(r'\b(\d{4}-\d{2}-\d{2})\b')
FINDING_RE = re.compile(r'^### +Finding +(\d+)\s*[—-]+\s*(.+?)\s*$', re.M)


def norm_id(kind, value):
    """One identifier -> its normalised key 'kind:value', or None."""
    k = kind.lower().strip(); v = str(value or '').strip().rstrip('.,;:)]\'"')
    if not v: return None
    if k == 'doi':
        v = re.sub(r'^(https?://(dx\.)?doi\.org/|doi:)', '', v, flags=re.I).lower()
        m = re.match(r'10\.48550/arxiv\.(.+)$', v)
        if m: k, v = 'arxiv', m.group(1)
    if k == 'arxiv': v = re.sub(r'v\d+$', '', re.sub(r'^(https?://arxiv\.org/abs/|arxiv:)', '', v, flags=re.I)).lower()
    elif k == 'pmid': v = re.sub(r'\D', '', v)
    elif k in ('pmcid', 'nct', 'celex'): v = v.upper()
    elif k == 'code':
        m = re.match(r'(?:local:)?(.+?)(?::\d+(?:-\d+)?)?@([0-9a-f]{7,40})$', v, re.I)  # file:line@SHA -> file@SHA7
        v = f'{m.group(1)}@{m.group(2)[:7].lower()}' if m else v
    elif k != 'doi': v = v.lower()
    return f'{k}:{v}' if v else None


def ids_in(text):
    return {x for x in (norm_id(k, v) for k, v in ID_RE.findall(text or '')) if x}


def title_key(title, year):
    t = ' '.join(re.findall(r'[a-z0-9]+', (title or '').lower()))
    return f'title:{t}|{year or ""}' if t else None


def load(p):
    try: return json.loads(p.read_text(encoding='utf-8'))
    except Exception: return None


def sections(t):
    parts = re.split(r'^## +(.+?)\s*$', t, flags=re.M)
    return {parts[i].strip(): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def run_T(d, report):
    r = load(d / 'run.json') or {}
    ts = r.get('T') if isinstance(r.get('T'), list) else [r.get('T')] if r.get('T') else []
    if not ts and (d / 'state' / 'journal.jsonl').exists():
        ts = sorted({l.get('T') for l in journal(d) if l.get('T')})
    if ts: return max(ts)
    for txt in ((d / 'scope.md').read_text(encoding='utf-8', errors='replace') if (d / 'scope.md').exists() else '', report):
        m = re.search(r'\bT\s*=\s*(\d{4}-\d{2}-\d{2})', txt)
        if m: return m.group(1)
    return None


def journal(d):
    out = []
    p = d / 'state' / 'journal.jsonl'
    for l in (p.read_text(encoding='utf-8', errors='replace').splitlines() if p.exists() else []):
        try: out.append(json.loads(l))
        except ValueError: pass
    return out


def header_of(d, key):
    """`id: ... | doi: ... | year: ... | date: ...` first line of sources/<key>/source.txt -> (ids, year, date)."""
    p = d / 'sources' / key / 'source.txt'
    if not p.exists(): return set(), None, None
    head = p.read_text(encoding='utf-8', errors='replace')[:2000].split('\n', 1)[0]
    f = dict((a.strip().lower(), b.strip()) for a, _, b in (x.partition(':') for x in head.split('|')) if b)
    ids = ids_in(f.get('id', '')) | ({norm_id(k, f[k]) for k in PREFIXES if f.get(k) and k != 'code'} - {None})
    date = (DATE_RE.search(f.get('date', '')) or [None])[0]
    return ids, (f.get('year') or '')[:4] or None, date


def read_run(d):
    d = pathlib.Path(d)
    card = load(d / 'card.json') or {}; report = (d / 'REPORT.md').read_text(encoding='utf-8', errors='replace')
    secs = sections(report); result = load(d / 'result.json') or {}; verdicts = load(d / 'verdicts.json') or {}
    by_id = {}
    for s in result.get('studies') or []:
        for i in ids_in(str(s.get('id', ''))): by_id[i] = s
    sources = {}
    for n, line in re.findall(r'^\s*\[(\d{1,3})\]\s*(.*)$', secs.get('Bibliography', ''), re.M):
        key = f'S{n}'; cs = (card.get('sources') or {}).get(key) or {}
        ids = ids_in(line) | ({norm_id(k, cs[k]) for k in PREFIXES if cs.get(k)} - {None})
        hids, hyear, hdate = header_of(d, key); ids |= hids
        st = next((by_id[i] for i in ids if i in by_id), {})
        years = re.findall(r'\b(19\d\d|20\d\d)\b', ID_RE.sub(' ', line))
        year = hyear or str(st.get('year') or '')[:4] or (years[-1] if years else None)
        title = cs.get('title') or st.get('title') or re.sub(r'\s+', ' ', ID_RE.sub('', line)).strip()[:160]
        flags = sorted({m.lower() for m in FLAG.findall(line + ' ' + json.dumps(st, ensure_ascii=False))})
        sources[key] = {'n': int(n), 'ids': sorted(ids), 'title': title, 'year': year, 'date': hdate, 'line': line.strip(), 'flags': flags,
                        'tkey': title_key(title, year)}
    for key, cs in (card.get('sources') or {}).items() if not sources else ():   # no bibliography entry read: card.sources stands for it
        if isinstance(cs, dict):
            ids = {norm_id(k, cs[k]) for k in PREFIXES if cs.get(k)} - {None}
            sources[key] = {'n': None, 'ids': sorted(ids), 'title': cs.get('title'), 'year': None,
                            'date': None, 'line': '', 'flags': [], 'tkey': title_key(cs.get('title'), None)}
    claim_src = {a.get('id'): (a.get('source') or {}).get('key') for a in card.get('claims') or []}
    status = {a.get('id'): a.get('status') for a in verdicts.get('claims') or []}
    counts = {s: 0 for s in STATUS_ORDER}
    for s in status.values(): counts[s] = counts.get(s, 0) + 1
    distorted = {}
    for cid, s in status.items():
        if s == 'DISTORTED' and claim_src.get(cid): distorted.setdefault(claim_src[cid], []).append(cid)
    findings = []
    ma = secs.get('Main Analysis', '')
    heads = list(FINDING_RE.finditer(ma))
    for i, m in enumerate(heads):
        body = ma[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(ma)]
        vl = next((re.sub(r'^\W+', '', l).strip() for l in body.splitlines() if re.match(r'^\W*verdict\b', l, re.I)), '')
        paren = re.findall(r'\(([^()]*)\)\s*$', m.group(2))
        findings.append({'n': int(m.group(1)), 'title': m.group(2), 'verdict': vl, 'words': verdict_words(vl or (paren[0] if paren else ''))})
    es = re.sub(r'\s+', ' ', secs.get('Executive Summary', '')).strip()
    paras = [p.strip() for p in re.split(r'\n\s*\n', secs.get('Methodology Appendix', '')) if p.strip()]
    vf = result.get('verification') if isinstance(result.get('verification'), dict) else {}
    return {'dir': str(d), 'T': run_T(d, report), 'question': card.get('question'), 'card_id': card.get('card_id'), 'sources': sources,
            'findings': findings, 'first_sentence': (re.match(r'(.+?[.!?])(\s|$)', es) or [None, es])[1], 'one_line': paras[-1] if paras else '',
            'counts': counts, 'claims': len(card.get('claims') or []), 'entries_removed': vf.get('entries_removed'),
            'distorted': distorted, 'seen': {i for l in journal(d) for i in ids_in(' '.join(map(str, l.get('ids') or [])))}}


def verdict_words(text):
    found = []
    for w in VERDICT_WORDS:   # NO-GO before GO: "GO" inside "NO-GO" is not counted twice
        for m in re.finditer(r'(?<![\w-])' + re.escape(w) + r'(?![\w-])', text, re.I if w.islower() else 0): found.append((m.start(), w))
    out = []
    for _, w in sorted(found):
        if w not in out: out.append(w)
    return out


def match_sources(old, new):
    """[(old key | None, new key | None)]: shared identifier first, then title + year."""
    pairs, used = [], set()
    idx = {}
    for k, s in old.items():
        for i in s['ids']: idx.setdefault(i, k)
    tidx = {s['tkey']: k for k, s in old.items() if s['tkey']}
    for k, s in sorted(new.items(), key=lambda x: x[1]['n'] or 0):
        o = next((idx[i] for i in s['ids'] if i in idx and idx[i] not in used), None)
        if o is None and s['tkey'] in tidx and tidx[s['tkey']] not in used: o = tidx[s['tkey']]
        if o: used.add(o)
        pairs.append((o, k))
    return pairs + [(k, None) for k in sorted(old, key=lambda x: old[x]['n'] or 0) if k not in used]


def similarity(a, b):
    na, nb = (' '.join(re.findall(r'[a-z0-9]+', re.sub(r'\([^()]*\)\s*$', '', x).lower())) for x in (a, b))
    ta, tb = set(na.split()), set(nb.split())
    return max(difflib.SequenceMatcher(None, na, nb).ratio(), len(ta & tb) / len(ta | tb) if ta | tb else 0)


def match_findings(old, new):
    cand = sorted(((similarity(o['title'], n['title']), i, j) for i, o in enumerate(old) for j, n in enumerate(new)), reverse=True)
    pairs, ui, uj = [], set(), set()
    for s, i, j in cand:
        if s >= MATCH_MIN and i not in ui and j not in uj: pairs.append((i, j, round(s, 2))); ui.add(i); uj.add(j)
    return pairs, [old[i] for i in range(len(old)) if i not in ui], [new[j] for j in range(len(new)) if j not in uj]


def classify(s, T1, seen_old):
    if s['date'] and T1: return 'new evidence' if s['date'] >= T1 else ('older, seen at T1 but not kept' if set(s['ids']) & seen_old else 'older, not found at T1')
    if s['year'] and T1 and s['year'].isdigit():
        if int(s['year']) > int(T1[:4]): return 'new evidence'
        if int(s['year']) == int(T1[:4]): return 'undetermined (same year as T1, no full date)'
    if not s['year']: return 'undetermined (no date)'
    return 'older, seen at T1 but not kept' if set(s['ids']) & seen_old else 'older, not found at T1'


def compare(old_dir, new_dir):
    o, n = read_run(old_dir), read_run(new_dir)
    pairs = match_sources(o['sources'], n['sources'])
    brief = lambda r, k: {'key': k, 'n': r['sources'][k]['n'], 'ids': r['sources'][k]['ids'], 'title': r['sources'][k]['title'],
                          'year': r['sources'][k]['year'], 'date': r['sources'][k]['date']}
    added = [dict(brief(n, k), status=classify(n['sources'][k], o['T'], o['seen'])) for ok, k in pairs if ok is None]
    dropped = [dict(brief(o, k), status='seen at T2 but not kept' if set(o['sources'][k]['ids']) & n['seen'] else 'not retrieved at T2')
               for k, nk in pairs if nk is None]
    kept = [{'old': ok, 'new': nk, 'ids': n['sources'][nk]['ids']} for ok, nk in pairs if ok and nk]
    fp, f_old, f_new = match_findings(o['findings'], n['findings'])
    changed, same = [], []
    for i, j, s in fp:
        a, b = o['findings'][i], n['findings'][j]
        e = {'old': {'n': a['n'], 'title': a['title'], 'verdict': a['verdict'], 'words': a['words']},
             'new': {'n': b['n'], 'title': b['title'], 'verdict': b['verdict'], 'words': b['words']}, 'similarity': s}
        (changed if a['words'] != b['words'] else same).append(e)
    changed.sort(key=lambda e: e['new']['n']); same.sort(key=lambda e: e['new']['n'])
    old_of = {nk: ok for ok, nk in pairs if ok and nk}
    flags_new = [{'new': k, 'n': s['n'], 'title': s['title'], 'flags': [f for f in s['flags'] if f not in o['sources'].get(old_of.get(k), {}).get('flags', [])]}
                 for k, s in n['sources'].items() if s['flags']]
    distorted_new = [{'new': k, 'n': n['sources'].get(k, {}).get('n'), 'claims': c} for k, c in n['distorted'].items() if not o['distorted'].get(old_of.get(k))]
    return {'old': {'dir': o['dir'], 'T': o['T'], 'question': o['question'], 'first_sentence': o['first_sentence'], 'one_line': o['one_line'],
                    'claims': o['claims'], 'counts': o['counts'], 'entries_removed': o['entries_removed'], 'sources': len(o['sources'])},
            'new': {'dir': n['dir'], 'T': n['T'], 'question': n['question'], 'first_sentence': n['first_sentence'], 'one_line': n['one_line'],
                    'claims': n['claims'], 'counts': n['counts'], 'entries_removed': n['entries_removed'], 'sources': len(n['sources'])},
            'same_question': (o['question'] or '').strip() == (n['question'] or '').strip(),
            'sources_kept': kept, 'sources_added': added, 'sources_dropped': dropped,
            'findings_verdict_changed': changed, 'findings_verdict_same': same,
            'findings_only_old': [{'n': f['n'], 'title': f['title'], 'words': f['words']} for f in f_old],
            'findings_only_new': [{'n': f['n'], 'title': f['title'], 'words': f['words']} for f in f_new],
            'newly_flagged': [x for x in flags_new if x['flags']], 'newly_distorted': distorted_new}


def clean(t):
    """Text safe to paste into REPORT.md: no angle brackets nor [n] (validate_card.py checks 3 and 11)."""
    return re.sub(r'\[(\d{1,3})\]', r'(\1)', re.sub(r'[<>]', '', str(t or ''))).strip()


def short(t, n=90):
    t = clean(t); return t if len(t) <= n else t[:n].rsplit(' ', 1)[0] + '...'


def paragraph(d):
    T1, T2 = d['old']['T'] or 'T1 unknown', d['new']['T'] or 'T2 unknown'
    new_ev = [s for s in d['sources_added'] if s['status'] == 'new evidence']
    older = [s for s in d['sources_added'] if s['status'].startswith('older')]
    und = [s for s in d['sources_added'] if s['status'].startswith('undetermined')]
    cite = lambda ss: ', '.join(f'[{s["n"]}]' if s['n'] else f'"{short(s["title"], 60)}"' for s in ss)
    p = [f'This report updates the run of {T1} on the same question{"" if d["same_question"] else " (question reworded: see update.json)"}; '
         f'the comparison is mechanical (`tools/living_diff.py`). Of the {d["new"]["sources"]} sources cited now, {len(d["sources_kept"])} were already cited at {T1}.']
    if new_ev: p.append(f'{len(new_ev)} {"is" if len(new_ev) == 1 else "are"} dated on or after {T1}, hence new evidence that could not be seen then: {cite(new_ev)}.')
    if older:
        seen = [s for s in older if 'seen' in s['status']]
        p.append(f'{len(older)} older source(s) were simply not cited at {T1}: {cite(older)}'
                 + (f' ({cite(seen)} had been seen then but not kept)' if seen else '') + '.')
    if und: p.append(f'For {cite(und)} the date does not tell whether it predates {T1}.')
    if d['sources_dropped']:
        p.append(f'{len(d["sources_dropped"])} source(s) cited at {T1} are no longer cited: '
                 + '; '.join(f'"{short(s["title"], 70)}" ({s["year"] or "no year"}, {s["status"]})' for s in d['sources_dropped']) + '.')
    if d['findings_verdict_changed']:
        p.append('Verdicts that changed: ' + '; '.join(f'Finding {c["new"]["n"]} ("{short(c["new"]["title"], 60)}") went from '
                 f'{"/".join(c["old"]["words"]) or "no verdict word"} to {"/".join(c["new"]["words"]) or "no verdict word"}' for c in d['findings_verdict_changed']) + '.')
    else: p.append('No verdict of a matched finding changed.')
    if d['findings_only_new']: p.append('New findings: ' + '; '.join(f'Finding {f["n"]}' for f in d['findings_only_new']) + '.')
    if d['findings_only_old']: p.append(f'Findings of {T1} without counterpart now: ' + '; '.join(f'"{short(f["title"], 60)}"' for f in d['findings_only_old']) + '.')
    if d['newly_flagged']: p.append('Newly flagged: ' + '; '.join(f'[{x["n"]}] ({", ".join(x["flags"])})' for x in d['newly_flagged']) + '.')
    if d['newly_distorted']: p.append('Sources carrying a DISTORTED claim now and none at the earlier run: ' + ', '.join(f'[{x["n"]}]' for x in d['newly_distorted'] if x['n']) + '.')
    co, cn = d['old']['counts'], d['new']['counts']
    p.append(f'Verification: {d["old"]["claims"]} claims checked at {T1} (FOUND {co.get("FOUND", 0)}, DISTORTED {co.get("DISTORTED", 0)}), '
             f'{d["new"]["claims"]} at {T2} (FOUND {cn.get("FOUND", 0)}, DISTORTED {cn.get("DISTORTED", 0)}).')
    return re.sub(r'[<>]', '', ' '.join(p))   # titles went through short(); the [n] left are the new report's numbers


def render(d):
    T1, T2 = d['old']['T'] or '?', d['new']['T'] or '?'
    L = [f'# Update: {T1} -> {T2}', '', f'Old run: `{d["old"]["dir"]}` (T = {T1}). New run: `{d["new"]["dir"]}` (T = {T2}).'
         + ('' if d['same_question'] else ' Warning: the two card.json questions differ.'), '',
         f'## Paragraph to paste (new report, Methodology Appendix, under `### What changed since {T1}`)', '', paragraph(d), '',
         '## Executive summaries, first sentence', '', f'- {T1}: {d["old"]["first_sentence"]}', f'- {T2}: {d["new"]["first_sentence"]}', '',
         '## One-line summaries', '', f'- {T1}: {d["old"]["one_line"]}', f'- {T2}: {d["new"]["one_line"]}', '',
         '## Sources', '', f'Cited: {d["old"]["sources"]} at {T1}, {d["new"]["sources"]} at {T2}; in both: {len(d["sources_kept"])}.', '']
    L += ['| new [n] | identifiers | year | date | status |', '|---|---|---|---|---|']
    L += [f'| [{s["n"]}] {short(s["title"], 60)} | {" ".join(s["ids"])} | {s["year"] or ""} | {s["date"] or ""} | {s["status"]} |' for s in d['sources_added']] or ['| none | | | | |']
    L += ['', '| dropped (old [n]) | identifiers | year | status |', '|---|---|---|---|']
    L += [f'| [{s["n"]}] {short(s["title"], 60)} | {" ".join(s["ids"])} | {s["year"] or ""} | {s["status"]} |' for s in d['sources_dropped']] or ['| none | | | |']
    L += ['', '## Findings', '']
    for c in d['findings_verdict_changed']:
        L += [f'- CHANGED (similarity {c["similarity"]}): Finding {c["old"]["n"]} "{c["old"]["title"]}" -> Finding {c["new"]["n"]} "{c["new"]["title"]}"',
              f'  - {T1}: {c["old"]["verdict"] or "no verdict line"}', f'  - {T2}: {c["new"]["verdict"] or "no verdict line"}']
    L += [f'- same verdict ({"/".join(c["new"]["words"]) or "no verdict word"}): Finding {c["old"]["n"]} -> Finding {c["new"]["n"]} "{c["new"]["title"]}"' for c in d['findings_verdict_same']]
    L += [f'- only at {T1}: Finding {f["n"]} "{f["title"]}"' for f in d['findings_only_old']]
    L += [f'- only at {T2}: Finding {f["n"]} "{f["title"]}"' for f in d['findings_only_new']]
    L += ['', '## Verification', '', '| status | ' + T1 + ' | ' + T2 + ' |', '|---|---|---|']
    L += [f'| {s} | {d["old"]["counts"].get(s, 0)} | {d["new"]["counts"].get(s, 0)} |' for s in sorted(set(d['old']['counts']) | set(d['new']['counts']), key=lambda x: (x not in STATUS_ORDER, STATUS_ORDER.index(x) if x in STATUS_ORDER else 0, x))]
    L += [f'| claims | {d["old"]["claims"]} | {d["new"]["claims"]} |', f'| result.json entries removed | {d["old"]["entries_removed"]} | {d["new"]["entries_removed"]} |', '']
    L += ['## Newly flagged', '']
    L += [f'- [{x["n"]}] {short(x["title"], 80)}: {", ".join(x["flags"])}' for x in d['newly_flagged']]
    L += [f'- [{x["n"]}] DISTORTED claims {", ".join(x["claims"])} (none on this source at {T1})' for x in d['newly_distorted']]
    if not d['newly_flagged'] and not d['newly_distorted']: L.append('None.')
    return '\n'.join(L) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); ap.add_argument('old'); ap.add_argument('new'); ap.add_argument('--out')
    a = ap.parse_args(argv)
    for x in (a.old, a.new):
        miss = [f for f in ('card.json', 'REPORT.md') if not (pathlib.Path(x) / f).is_file()]
        if miss: print(f'{x}: missing {", ".join(miss)}', file=sys.stderr); return 2
    d = compare(a.old, a.new)
    out = pathlib.Path(a.out) if a.out else pathlib.Path(a.new) / 'UPDATE.md'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(d), encoding='utf-8')
    js = out.with_name('update.json') if out.name == 'UPDATE.md' else out.with_suffix('.json')
    js.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
    print(out); print(js); return 0


if __name__ == '__main__':
    sys.exit(main())
