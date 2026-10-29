#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""End-of-run message (SKILL.md section 8): SUMMARY.md, the short text the assistant copies as is into the conversation, and summary.json.
Standard library, no network, no model; run by finish_run.py after the exports, or alone. Written in the language of the run
(tools/report_lang.py: `Report language:` of scope.md, else the titles of REPORT.md). Content, from the run's files only:
  answer      the first `summary.answer_sentences` sentences of the Executive Summary (citations [n] removed, at most `summary.answer_chars`)
  confidence  high / medium / low from the share of FOUND among ALL the claims the verifier judged, read on its raw output, BEFORE the
              removals of section 7 (state/verifier.json `summary`; else verdicts.json plus the removed claims it still lists: `removed`,
              `filter.removed`); never on the edited verdicts.json alone, where the ABSENT are already gone (23 FOUND of 41 would read 23 of 23).
              Without a raw output: `unknown`. Thresholds `summary.confidence`; one level lower when fewer than `summary.min_sources`
              bibliography entries carry the report; with the finding verdicts counted
  verification  "N claims verified, of which X FOUND" on the same raw counts (ABSENT, DISTORTED... listed: removed afterwards)
  cost        --cost-usd when the host reports it; else the sum of the receipts of the nested calls (state/verifier.json, whole reading,
              contradictor.json), stated as partial; else "not known"
  duration    from state/run-start.json (tools/new_run.py) or the first gateway call, to the end of finish_run.py (state/finish_run.json)
  report      absolute paths of REPORT.html and REPORT.pdf (a follow-up: the parent's FOLLOWUP-<n>.html / .pdf)
summary.json adds `attach`: the file a host that can attach one sends with the message (the PDF when it exists, else the HTML).
Usage: summary.py RUN_DIR [--cost-usd USD] [--lang CODE] [--json]      Prints SUMMARY.md. Exit 0; 2 when RUN_DIR has no REPORT.md.
Import: build(dir, cost_usd=None, lang=None) -> dict; render(data) -> str."""
import argparse, datetime as dt, json, pathlib, re, sys
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P))
import report_lang as RL   # noqa: E402

CFG = json.loads((P / 'config.json').read_text(encoding='utf-8')).get('summary') or {}
SENTENCES = int(CFG.get('answer_sentences', 3)); CHARS = int(CFG.get('answer_chars', 500))
LEVELS = CFG.get('confidence') or {'high': 0.9, 'medium': 0.75}; MIN_SOURCES = int(CFG.get('min_sources', 10))
SCALE = list(RL.LANGS['en']['verdicts'])       # established, probable, possible, open, unlikely, refuted
ORDER = ['FOUND', 'DISTORTED', 'SOURCE-UNAVAILABLE', 'UNVERIFIED', 'ABSENT', 'INVALID']


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
    return round(sum(parts), 2) if parts else None


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


def build(folder, cost_usd=None, lang=None):
    d = pathlib.Path(folder).resolve()
    md = _text(d / 'REPORT.md')
    lang = lang if lang in RL.LANGS else RL.of_run(d)
    counts, basis = raw_counts(d)
    n = sum(counts.values()); found = counts.get('FOUND', 0)
    bib = len(re.findall(r'^\s*\[(\d{1,3})\]', RL.section(md, 'Bibliography'), re.M))
    if not n or basis == 'verdicts': level = 'unknown'      # removals unknown: a share on the kept claims alone would overstate it
    else:
        share = found / n
        level = 'high' if share >= LEVELS['high'] else 'medium' if share >= LEVELS['medium'] else 'low'
        if bib < MIN_SOURCES: level = {'high': 'medium', 'medium': 'low'}.get(level, level)
    fu = _json(d / 'followup.json')
    base, stem = (pathlib.Path(fu['parent']).resolve(), f"FOLLOWUP-{fu['n']}") if isinstance(fu, dict) and fu.get('parent') and fu.get('n') else (d, 'REPORT')
    html_p, pdf_p = base / f'{stem}.html', base / f'{stem}.pdf'
    if not html_p.exists() and (d / 'REPORT.html').exists(): html_p, pdf_p = d / 'REPORT.html', d / 'REPORT.pdf'
    if cost_usd is not None: cost, kind = round(float(cost_usd), 2), 'host'
    else:
        cost = known_costs(d); kind = 'partial' if cost is not None else 'unknown'
    return {'dir': str(d), 'language': lang, 'answer': answer(md), 'level': level, 'claims': n, 'found': found, 'counts': counts, 'counts_basis': basis,
            'found_share': round(found / n, 3) if n else None, 'bibliography_entries': bib, 'finding_verdicts': finding_verdicts(md),
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
    L = x['language']; c = RL.msg(L, 'colon'); M = lambda key_, **kw: RL.msg(L, key_, **kw)
    lines = []
    if x['followup']: lines.append(f"**{M('followup', n=x['followup'])}**")
    lines.append(f"**{M('answer')}**{c}{x['answer'] or '-'}")
    detail = []
    if x['claims'] and x.get('counts_basis') != 'verdicts': detail.append(M('found_share', found=x['found'], n=x['claims'], pct=100 * x['found'] // x['claims']))
    if x['bibliography_entries'] < MIN_SOURCES and x['claims']: detail.append(M('few_sources', k=MIN_SOURCES))
    if x['finding_verdicts']:
        detail.append(M('findings_verdicts', v=', '.join(f'{_verdict_label(L, k)} {v}' for k, v in sorted(x['finding_verdicts'].items(), key=lambda kv: SCALE.index(kv[0]) if kv[0] in SCALE else 99))))
    lines.append(f"**{M('confidence')}**{c}{M('level')[x['level']]}" + (f" ({(' ; ' if c.startswith(' ') else '; ').join(detail)})" if detail else ''))
    others = ', '.join(f'{k} {x["counts"][k]}' for k in ORDER if k != 'FOUND' and x['counts'].get(k))
    lines.append(f"**{M('verification')}**{c}{M('claims_found', n=x['claims'], found=x['found'])}" + (f' ({others})' if others else ''))
    usd = None if x['cost_usd'] is None else f"{x['cost_usd']:.2f}"
    lines.append(f"**{M('cost')}**{c}" + (M('cost_given', usd=usd) if x['cost_kind'] == 'host' else M('cost_partial', usd=usd) if x['cost_kind'] == 'partial' else M('cost_unknown')))
    if (du := _dur(L, x['duration_s'])): lines.append(f"**{M('duration')}**{c}{du}")
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
