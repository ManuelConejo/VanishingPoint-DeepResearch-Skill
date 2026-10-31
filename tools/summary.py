#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""End-of-run message (SKILL.md section 8): SUMMARY.md, the short text the assistant copies as is into the conversation, and summary.json.
Standard library, no network, no model; run by finish_run.py after the exports, or alone. Written in the language of the run
(tools/report_lang.py: `Report language:` of scope.md, else the titles of REPORT.md). Content, from the run's files only:
  answer      the first `summary.answer_sentences` sentences of the Executive Summary (citations [n] removed, at most `summary.answer_chars`)
  citations   "Citations confirmed: X of N checked": the FOUND (the claim is in its cited source) among ALL the claims the verifier
              judged, read on its raw output, BEFORE the removals of section 7 (state/verifier.json `summary`; else verdicts.json plus the
              removed claims it still lists: `removed`, `filter.removed`); never on the edited verdicts.json alone, where the ABSENT are
              already gone (23 FOUND of 41 would read 23 of 23): that case is shown as the kept claims, removals unknown. Then the other
              statuses (ABSENT, DISTORTED...) and "K removed from the report after verification": K = raw claims minus the claims left in
              verdicts.json (basis 'verifier'), or the removed claims verdicts.json lists (basis 'verdicts+removed'); not shown when unknown
              or 0. Claims the contradictor added or changed (SKILL.md "On request after delivery": verified apart into
              verdicts-contradictor.json, without --state, then merged into verdicts.json) are added to the raw counts of
              state/verifier.json and named ("K checked after the contradictor"); a changed claim counts its first wording as
              removed. This measures attribution (is the claim in its source), not coverage nor the certainty of the answer: no "confidence"
              level is derived from it (external audit of 2026-10-29).
  coverage    what can be counted mechanically: the research angles of scope.md reached by at least one kept source (an angle is reached
              when a searches/<n>.md file that names it in its first lines holds the identifier of a card.json source); the distinct
              studies of the bibliography (tools/study_family.py: versions of one study count once), with the notice "fewer than
              `summary.min_sources`" when it applies; the finding verdicts counted
  cost        --cost-usd when the host reports it; else the sum of the receipts of the nested calls (state/verifier.json, whole reading,
              contradictor.json, verdicts-contradictor.json), stated as partial; else "not known"
  duration    from state/run-start.json (tools/new_run.py) or the first gateway call, to the end of finish_run.py (state/finish_run.json)
  report      absolute paths of REPORT.html and REPORT.pdf (a follow-up: the parent's FOLLOWUP-<n>.html / .pdf)
summary.json adds `attach`: the file a host that can attach one sends with the message (the PDF when it exists, else the HTML).
Usage: summary.py RUN_DIR [--cost-usd USD] [--lang CODE] [--json]      Prints SUMMARY.md. Exit 0; 2 when RUN_DIR has no REPORT.md.
Import: build(dir, cost_usd=None, lang=None) -> dict; render(data) -> str."""
import argparse, datetime as dt, json, pathlib, re, sys
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P))
import report_lang as RL   # noqa: E402
import study_family as SF   # noqa: E402

CFG = json.loads((P / 'config.json').read_text(encoding='utf-8')).get('summary') or {}
SENTENCES = int(CFG.get('answer_sentences', 3)); CHARS = int(CFG.get('answer_chars', 500))
MIN_SOURCES = int(CFG.get('min_sources', 10)); ANGLE_LINES = int(CFG.get('angle_header_lines', 5))
SCALE = list(RL.LANGS['en']['verdicts'])       # established, probable, possible, open, unlikely, refuted
ORDER = ['FOUND', 'DISTORTED', 'SOURCE-UNAVAILABLE', 'UNVERIFIED', 'ABSENT', 'INVALID']
CONTRA_VERDICTS = 'verdicts-contradictor.json'   # the --out SKILL.md ("Contradictor", on request after delivery) gives verifier.py


def _json(p):
    try: return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError): return None


def _text(p):
    try: return pathlib.Path(p).read_text(encoding='utf-8', errors='replace')
    except OSError: return ''


def _utc(s):
    try: return dt.datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except (TypeError, ValueError): return None


def answer(md):
    es = RL.section(md, 'Executive Summary')
    t = re.sub(r'\s*\[\d{1,3}(?:\s*[,;–-]\s*\d{1,3})*\]', '', es)
    t = re.sub(r'[*_`]{1,2}', '', re.sub(r'^#+.*$', '', t, flags=re.M))
    t = ' '.join(t.split())
    sents = re.split(r'(?<=[.!?])\s+(?=[^\s\da-z])', t)
    out = ' '.join(sents[:SENTENCES]).strip()
    if len(out) > CHARS: out = out[:CHARS].rsplit(' ', 1)[0].rstrip(',;:') + ' …'
    return out


def finding_verdicts(md):
    ma = RL.section(md, 'Main Analysis'); heads = list(RL.finding_re().finditer(ma)); out = {}
    label = re.compile(r'\b(?:' + '|'.join(L['verdict_label'] for L in RL.LANGS.values()) + r')\b([^\n]{0,200})', re.I)
    for i, m in enumerate(heads):
        body = ma[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(ma)]
        v = label.search(body)
        w = RL.verdict_word(v.group(1)) if v else None
        if w: out[w] = out.get(w, 0) + 1
    return out


def duration(d):
    start = _utc((_json(d / 'state' / 'run-start.json') or {}).get('created_utc'))
    if not start:
        try:
            first = next((json.loads(l) for l in _text(d / 'state' / 'journal.jsonl').splitlines() if l.strip()), {})
            start = _utc(first.get('utc'))
        except ValueError: start = None
    fin = _json(d / 'state' / 'finish_run.json') or {}
    end = _utc(fin.get('finished_utc') or fin.get('started_utc'))
    if not end:
        lines = [l for l in _text(d / 'state' / 'journal.jsonl').splitlines() if l.strip()]
        try: end = _utc(json.loads(lines[-1]).get('utc')) if lines else None
        except ValueError: end = None
    return (end - start).total_seconds() if start and end and end >= start else None


def known_costs(d):
    """Sum of the costs the receipts of nested model calls record (USD), or None when no receipt records one."""
    parts = []
    v = _json(d / 'state' / 'verifier.json')
    if isinstance(v, dict) and isinstance(v.get('cost_usd'), (int, float)): parts.append(float(v['cost_usd']))
    w = _json(d / 'state' / 'whole-reading' / 'receipt.json')
    if isinstance(w, dict) and isinstance(w.get('usd'), (int, float)): parts.append(float(w['usd']))
    c = _json(d / 'contradictor.json')
    if isinstance(c, dict) and isinstance((c.get('cost_usd') or {}).get('total'), (int, float)): parts.append(float(c['cost_usd']['total']))
    vc = _json(d / CONTRA_VERDICTS)
    if isinstance(vc, dict) and isinstance(vc.get('cost_usd'), (int, float)) and not isinstance(vc.get('cost_usd'), bool): parts.append(float(vc['cost_usd']))
    return round(sum(parts), 2) if parts else None


def _status_counts(ver):
    """Raw counts of one verifier output: its `summary` when it has one, else its claims plus the removed claims it still lists, by id."""
    if not isinstance(ver, dict): return {}
    s = ver.get('summary')
    if isinstance(s, dict):
        c = {k: int(x) for k, x in s.items() if k in ORDER and isinstance(x, int) and not isinstance(x, bool) and x > 0}
        if c: return c
    f = ver.get('filter') if isinstance(ver.get('filter'), dict) else {}
    seen = {}
    for i, c in enumerate(list(ver.get('claims') or []) + list(ver.get('removed') or []) + list(f.get('removed') or [])):
        if isinstance(c, dict): seen.setdefault(str(c.get('id') or f'#{i}'), str(c.get('status')))
    out = {}
    for st in seen.values(): out[st] = out.get(st, 0) + 1
    return out


def contradictor_counts(d):
    """Raw counts of the separate verification of the claims the contradictor added or changed (verdicts-contradictor.json), or {}."""
    return _status_counts(_json(d / CONTRA_VERDICTS))


def raw_counts(d):
    """Counts of the verifier's verdicts BEFORE the removals of section 7 -> (counts, basis).
    basis 'verifier': state/verifier.json `summary` (written by verifier.py --state, never edited by the orchestrator);
    'verdicts+removed': verdicts.json claims plus the removed claims it still lists (`removed`, `filter.removed`), by id;
    'verdicts': verdicts.json alone, removals unknown (the confidence is then `unknown`); None: no verdicts at all."""
    v = _json(d / 'state' / 'verifier.json')
    s = v.get('summary') if isinstance(v, dict) else None
    if isinstance(s, dict):
        c = {k: int(x) for k, x in s.items() if k in ORDER and isinstance(x, int) and not isinstance(x, bool) and x > 0}
        if c: return c, 'verifier'
    ver = _json(d / 'verdicts.json')
    if not isinstance(ver, dict): return {}, None
    seen = {}
    rem = list(ver.get('removed') or []) + list((ver.get('filter') or {}).get('removed') or [] if isinstance(ver.get('filter'), dict) else [])
    for i, c in enumerate(list(ver.get('claims') or []) + rem):
        if isinstance(c, dict): seen.setdefault(str(c.get('id') or f'#{i}'), str(c.get('status')))
    counts = {}
    for st in seen.values(): counts[st] = counts.get(st, 0) + 1
    return counts, ('verdicts+removed' if any(isinstance(c, dict) for c in rem) else 'verdicts') if counts else None


def removed_count(d, counts, basis):
    """Claims removed from the report after verification (section 7), or None when it cannot be known.
    basis 'verifier': raw total minus the claims still in verdicts.json; 'verdicts+removed': the removed ids verdicts.json still lists
    that are no longer among its claims; 'verdicts' / None: unknown."""
    ver = _json(d / 'verdicts.json')
    if not isinstance(ver, dict) or not isinstance(ver.get('claims'), list): return None
    kept = {str(c.get('id') or f'#{i}') for i, c in enumerate(ver['claims']) if isinstance(c, dict)}
    if basis == 'verifier': return max(0, sum(counts.values()) - len(kept))
    if basis == 'verdicts+removed':
        f = ver.get('filter') if isinstance(ver.get('filter'), dict) else {}
        rem = {str(c.get('id')) for c in list(ver.get('removed') or []) + list(f.get('removed') or []) if isinstance(c, dict) and c.get('id')}
        return len(rem - kept)
    return None


def _angle_numbers(text):
    """Angle numbers a searches/<n>.md names in its first lines: "angle 3", "angles 1 and 2", "angles 4,5,6", "angles 4-6",
    "Angles: 1 (meta-analyses), 5 (bias)"."""
    out = set()
    for line in re.finditer(r'\bangles?\b\s*[:=]?([^\n]*)', text, re.I):
        rest = re.sub(r'\([^)]*\)', ' ', line.group(1)).split('.')[0]          # "Angles: 1 (meta-analyses), 5 (bias). T = ..."
        m = re.match(r'\s*(\d{1,2}(?:\s*(?:,|;|and|et|y|und|&|-|–|to|à)\s*\d{1,2})*)', rest, re.I)
        if not m: continue
        for a, b in re.findall(r'(\d{1,2})(?:\s*(?:-|–|to|à)\s*(\d{1,2}))?', m.group(1)):
            out |= set(range(int(a), int(b) + 1)) if b else {int(a)}
    return out


def angle_coverage(d):
    """(angles of scope.md reached by at least one kept source, angles of scope.md), or None when it cannot be counted (no numbered
    angles, or no searches/ file naming its angles)."""
    try:
        import resume as _rs
        angles = {int(a) for a in _rs.angles(_text(d / 'scope.md'))}
    except Exception: return None
    files = sorted((d / 'searches').glob('*.md')) if (d / 'searches').is_dir() else []
    card = _json(d / 'card.json') or {}
    vals = set()
    for x in (card.get('sources') or {}).values() if isinstance(card.get('sources'), dict) else ():
        for f, v in (x or {}).items() if isinstance(x, dict) else ():
            if f in SF.NOT_IDS or not isinstance(v, str): continue
            v = v.strip().casefold(); base = v.rsplit('@', 1)[0] if f in ('code', 'local') else v   # <path>@<SHA>: the path is what a searcher writes
            vals |= {w for w in (v, base) if len(w) >= 4}
    named, reached = set(), set()
    for p in files:
        t = _text(p); a = _angle_numbers('\n'.join(t.splitlines()[:ANGLE_LINES])) & angles
        named |= a; low = t.casefold()
        if a and any(re.search(r'(?<![\w.])' + re.escape(v) + r'(?![\w])', low) for v in vals): reached |= a
    if not angles or not named: return None
    return len(reached), len(angles)


def build(folder, cost_usd=None, lang=None):
    d = pathlib.Path(folder).resolve()
    md = _text(d / 'REPORT.md')
    lang = lang if lang in RL.LANGS else RL.of_run(d)
    counts, basis = raw_counts(d)
    contra = contradictor_counts(d)
    if basis == 'verifier' and contra:          # the first pass's receipt never holds them; verdicts.json (other bases) already does
        counts = {k: counts.get(k, 0) + contra.get(k, 0) for k in ORDER if counts.get(k, 0) + contra.get(k, 0)}
    n = sum(counts.values()); found = counts.get('FOUND', 0)
    bib = len(re.findall(r'^\s*\[(\d{1,3})\]', RL.section(md, 'Bibliography'), re.M))
    fam = SF.families(_json(d / 'card.json') or {}, md); studies = fam['studies'] if bib else 0
    cov = angle_coverage(d)
    fu = _json(d / 'followup.json')
    base, stem = (pathlib.Path(fu['parent']).resolve(), f"FOLLOWUP-{fu['n']}") if isinstance(fu, dict) and fu.get('parent') and fu.get('n') else (d, 'REPORT')
    html_p, pdf_p = base / f'{stem}.html', base / f'{stem}.pdf'
    if not html_p.exists() and (d / 'REPORT.html').exists(): html_p, pdf_p = d / 'REPORT.html', d / 'REPORT.pdf'
    if cost_usd is not None: cost, kind = round(float(cost_usd), 2), 'host'
    else:
        cost = known_costs(d); kind = 'partial' if cost is not None else 'unknown'
    return {'dir': str(d), 'language': lang, 'answer': answer(md), 'claims': n, 'found': found, 'counts': counts, 'counts_basis': basis,
            'removed': removed_count(d, counts, basis), 'contradictor_checked': sum(contra.values()),
            'found_share': round(found / n, 3) if n and basis != 'verdicts' else None, 'bibliography_entries': bib, 'studies': studies,
            'study_families': [g['members'] for g in fam['groups']], 'angles_reached': cov[0] if cov else None, 'angles': cov[1] if cov else None,
            'finding_verdicts': finding_verdicts(md),
            'cost_usd': cost, 'cost_kind': kind, 'duration_s': duration(d),
            'report_html': str(html_p) if html_p.exists() else None, 'report_pdf': str(pdf_p) if pdf_p.exists() else None,
            'attach': str(pdf_p) if pdf_p.exists() else (str(html_p) if html_p.exists() else None),
            'followup': fu.get('n') if isinstance(fu, dict) else None}


def _dur(lang, s):
    if s is None: return None
    m = max(1, round(s / 60))
    return RL.msg(lang, 'minutes', m=m) if m < 60 else RL.msg(lang, 'hours', h=m // 60, m=m % 60)


def _verdict_label(lang, en):
    return next((w for w, e in RL.LANGS[lang]['verdicts'].items() if e == en), en)


def render(x):
    """At most six lines: answer (with the follow-up number), citations confirmed, coverage, cost, duration, report."""
    L = x['language']; c = RL.msg(L, 'colon'); M = lambda key_, **kw: RL.msg(L, key_, **kw)
    sep = ' ; ' if c.startswith(' ') else '; '
    lines = []
    head = (M('followup', n=x['followup']) + ' — ' if x['followup'] else '') + M('answer')
    lines.append(f"**{head}**{c}{x['answer'] or '-'}")
    others = ', '.join(f'{k} {x["counts"][k]}' for k in ORDER if k != 'FOUND' and x['counts'].get(k))
    if not x['claims']: cit = M('citations_none')
    elif x.get('counts_basis') == 'verdicts': cit = M('citations_kept', found=x['found'], n=x['claims'])
    else:
        extra = [e for e in (others, M('removed', k=x['removed']) if x.get('removed') else '',
                             M('contra_checked', k=x['contradictor_checked']) if x.get('contradictor_checked') else '') if e]
        cit = sep.join([M('citations_found', found=x['found'], n=x['claims'], pct=100 * x['found'] // x['claims'])] + extra)
    lines.append(f"**{M('citations')}**{c}{cit}")
    cov = []
    if x.get('angles'): cov.append(M('angles_reached', k=x['angles_reached'], n=x['angles']))
    if x['bibliography_entries']:
        cov.append(M('studies', s=x['studies'], b=x['bibliography_entries']) if x['studies'] != x['bibliography_entries'] else M('sources', b=x['bibliography_entries']) if x['bibliography_entries'] > 1 else M('source_one'))
        if x['studies'] < MIN_SOURCES: cov.append(M('few_sources', k=MIN_SOURCES))
    if x['finding_verdicts']:
        cov.append(M('findings_verdicts', v=', '.join(f'{_verdict_label(L, k)} {v}' for k, v in sorted(x['finding_verdicts'].items(), key=lambda kv: SCALE.index(kv[0]) if kv[0] in SCALE else 99))))
    if cov: lines.append(f"**{M('coverage')}**{c}{sep.join(cov)}")
    usd = None if x['cost_usd'] is None else f"{x['cost_usd']:.2f}"
    cost = M('cost_given', usd=usd) if x['cost_kind'] == 'host' else M('cost_partial', usd=usd) if x['cost_kind'] == 'partial' else M('cost_unknown')
    du = _dur(L, x['duration_s'])
    lines.append(f"**{M('cost')}**{c}{cost}")
    if du: lines.append(f"**{M('duration')}**{c}{du}")
    rep = x['report_html'] or x['dir']
    lines.append(f"**{M('report')}**{c}{rep}" + (f" ({M('pdf')}{c}{x['report_pdf']})" if x['report_pdf'] else ''))
    return '\n'.join(lines) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description='SUMMARY.md: the end-of-run message (no model).')
    ap.add_argument('run_dir'); ap.add_argument('--cost-usd', type=float); ap.add_argument('--lang'); ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    d = pathlib.Path(a.run_dir)
    if not (d / 'REPORT.md').is_file(): print(f'summary.py: no REPORT.md in {a.run_dir}', file=sys.stderr); return 2
    x = build(d, a.cost_usd, a.lang); text = render(x)
    (d / 'SUMMARY.md').write_text(text, encoding='utf-8')
    (d / 'summary.json').write_text(json.dumps(x, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(x, ensure_ascii=False, indent=1) if a.json else text, end='' if not a.json else '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
