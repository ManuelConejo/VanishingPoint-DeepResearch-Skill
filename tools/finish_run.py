#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""End of a run in one command (SKILL.md section 8, plus the shared retraction rule of the plugins). Standard library, no model.
Usage: finish_run.py RUN_DIR [--T YYYY-MM-DD] [--plugin plugins/law.md ...] [--offline] [--rw-csv FILE] [--json]
                     [--prisma] [--followups] [--prior-art]
Optional steps (never by default; SKILL.md, optional sections): --prisma writes PRISMA.md / PRISMA.svg / prisma.json (tools/prisma.py) and
appends the diagram to REPORT.html; --followups writes FOLLOWUPS.md / followups.json (tools/followups.py) and appends them to REPORT.html;
--prior-art ("Prior art?" mode) first writes PRIOR-ART.md (tools/prior_art.py), then validates with validate_card.py --prior-art and skips
validate_result (no result.json in that mode).
Runs, in this order, each step whatever the others gave (status ok | problems | skipped, with the reason):
  1 validate_card.py DIR --header (--header skipped without state/journal.jsonl)   2 validate_result.py DIR/result.json
  3 retraction check (below; writes DIR/retractions.json)   4 law_checks.py DIR (only when a law plugin is used: --plugin, else scope.md)
  5 export_report.py DIR --pdf --open (with the cited passages under each bibliography entry)   6 export_data.py DIR (also passages.json,
  PASSAGES.md: tools/passages.py)
Exit code 0 only when steps 1 and 2 passed; the paths of the files produced are printed at the end.
Receipt: DIR/state/finish_run.json (fingerprints of REPORT.md, card.json, result.json, verdicts.json taken before the steps, then the steps and
their statuses). `validate_card.py DIR` (check 13, gateway runs) refuses a run without it or whose files changed after it: the run cannot be
delivered clean without this command. The verifier's receipt (DIR/state/verifier.json: full texts attempted / obtained, gateway pool) is
summarised under `verification`, informative.
Retraction check (rule shared by all plugins: "Mechanical retraction check"): for every DOI of card.json `sources`, Crossref `/works/<DOI>`
(`updated-by`, and `update-to` when the DOI is itself a notice), then, when the record carries no `updated-by`, the notices pointing to it
(`/works?filter=updates:<DOI>`, their `update-to`). Retraction Watch: the update entries Crossref serves with source `retraction-watch`, and
the CSV `crossref/retraction-watch-data` when given (--rw-csv; columns OriginalPaperDOI, RetractionNature). State per DOI:
retracted | concern | erratum | none (Crossref answered, no notice) | unknown (no answer: offline, network, error); `unknown` is never
turned into `none`. Network through gateway.fetch (polite User-Agent / VP_CONTACT, per-host interval, retries), cache in DIR/state/cache;
--offline: cache only. Current state of the record, not dated at T (a retraction after T still matters for the reader).
Import: finish(dir, T=None, plugins=(), offline=False, rw_csv=None) -> dict ; retractions(dir, offline=False, rw_csv=None) -> dict."""
import argparse, csv, datetime as dt, hashlib, json, os, pathlib, re, subprocess, sys, urllib.parse
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P))
import gateway as gw   # noqa: E402  (fetch, _mailto: the gateway's polite HTTP pattern)
import validate_card as vc   # noqa: E402  (fingerprints of the end-step inputs, check 13)

STATE_OF = {'retraction': 'retracted', 'partial_retraction': 'retracted', 'withdrawal': 'retracted', 'removal': 'retracted',
            'expression_of_concern': 'concern', 'erratum': 'erratum', 'correction': 'erratum', 'corrigendum': 'erratum'}
RANK = ['unknown', 'none', 'erratum', 'concern', 'retracted']   # order of severity among answered states (unknown kept apart)
RW_NATURE = {'retraction': 'retraction', 'expression of concern': 'expression_of_concern', 'correction': 'correction'}
DOI = re.compile(r'^10\.\d{4,9}/\S+$')
TIMEOUT = 600


def _norm(doi): return re.sub(r'^(https?://(dx\.)?doi\.org/|doi:)', '', str(doi or '').strip(), flags=re.I).lower()


def _updates(items):
    """Crossref update entries ({DOI, type, source, updated}) -> [{type, doi, source, date}] (the caller keeps those about its DOI)."""
    out = []
    for u in items or []:
        if not isinstance(u, dict): continue
        d = (u.get('updated') or {}).get('date-parts') or [[None]]
        out.append({'type': str(u.get('type') or '').lower(), 'doi': _norm(u.get('DOI')) or None, 'source': u.get('source') or 'crossref',
                    'date': '-'.join(f'{x:02d}' if i else str(x) for i, x in enumerate(d[0] or []) if isinstance(x, int)) or None})
    return out


def _get(url, offline):
    """JSON through gateway.fetch; offline: cache only. None = no answer (the state stays unknown)."""
    if offline:
        c = gw.STATE / 'cache' / hashlib.sha256(url.encode()).hexdigest()   # the gateway's cache key (no headers)
        return json.loads(c.read_bytes()) if c.exists() else None
    return json.loads(gw.fetch(url))


def _rw_rows(path):
    """Retraction Watch CSV -> {doi: [update entries]} (OriginalPaperDOI, RetractionNature, RetractionDate)."""
    out = {}
    with open(path, encoding='utf-8', errors='replace', newline='') as f:
        for r in csv.DictReader(f):
            d = _norm(r.get('OriginalPaperDOI'))
            t = RW_NATURE.get(str(r.get('RetractionNature') or '').strip().lower())
            if d and t: out.setdefault(d, []).append({'type': t, 'doi': None, 'source': 'retraction-watch-csv', 'date': r.get('RetractionDate') or None})
    return out


def check_doi(doi, offline=False, rw=None):
    """One DOI -> {doi, state, updates, retraction_watch, error?}. Never invents: no answer -> unknown."""
    q = urllib.parse.quote(doi, safe='/:;()._-')
    r = {'doi': doi, 'state': 'unknown', 'updates': [], 'retraction_watch': False}
    try:
        w = _get(f'https://api.crossref.org/works/{q}' + gw._mailto('?'), offline)
        if w is None: r['error'] = 'not in cache (offline)'
        else:
            m = w.get('message') or {}
            ups = _updates(m.get('updated-by'))
            if m.get('update-to'): r['is_notice_for'] = [u['doi'] for u in _updates(m.get('update-to'))]
            if 'updated-by' not in m:
                n = _get('https://api.crossref.org/works?rows=50&filter=' + urllib.parse.quote('updates:' + doi, safe=':/') + gw._mailto(), offline)
                if n is None: r['error'] = 'notices not in cache (offline)'
                else:
                    for it in (n.get('message') or {}).get('items') or []:
                        ups += [u for u in _updates(it.get('update-to')) if u['doi'] in (None, doi)]
            r['updates'] = ups
            if 'error' not in r: r['state'] = 'none'
    except Exception as e:   # network, HTTP, JSON: the state stays unknown, with the reason
        r['error'] = f'{type(e).__name__}: {getattr(e, "code", "") or e}'[:200]
    if rw is not None and rw.get(doi): r['updates'] += rw[doi]
    states = [STATE_OF[u['type']] for u in r['updates'] if u['type'] in STATE_OF]
    if states: r['state'] = max(states, key=RANK.index)   # a notice found (Crossref or RW CSV) is a fact even if another call failed
    r['retraction_watch'] = any('retraction-watch' in str(u['source']) for u in r['updates'])
    return r


def retractions(d, offline=False, rw_csv=None):
    """Every DOI of card.json -> DIR/retractions.json; {'checked_utc', 'sources': {key: result}, 'summary': {state: n}}."""
    d = pathlib.Path(d); card = json.loads((d / 'card.json').read_text(encoding='utf-8'))
    gw.STATE = d / 'state'
    gw.STOP['api.crossref.org'] = tuple(set(gw.STOP.get('api.crossref.org', ())) | {404})   # DOI unknown to Crossref (DataCite...): no retry, state unknown
    rw = _rw_rows(rw_csv) if rw_csv else None
    res, net_down = {}, False
    for k, s in (card.get('sources') or {}).items():
        doi = _norm((s or {}).get('doi')) if isinstance(s, dict) else ''
        if not doi: continue
        if not DOI.match(doi): res[k] = {'doi': doi, 'state': 'unknown', 'updates': [], 'retraction_watch': False, 'error': 'not a DOI'}; continue
        res[k] = check_doi(doi, offline or net_down, rw)
        if not offline and str(res[k].get('error', '')).startswith('URLError'): net_down = True   # no network: the rest from the cache only
    out = {'checked_utc': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'rule': 'plugins, "Mechanical retraction check"',
           'retraction_watch_csv': bool(rw_csv), 'sources': res, 'summary': {s: sum(r['state'] == s for r in res.values()) for s in RANK}}
    (d / 'retractions.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    return out


def _run(args):
    """A tool of tools/ as `python3 -I`; -> (exit code, output). Never raises."""
    try:
        p = subprocess.run([sys.executable, '-I', str(P / args[0])] + [str(a) for a in args[1:]], capture_output=True, text=True, timeout=TIMEOUT)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as e:
        return 99, f'{type(e).__name__}: {e}'


def _paths(text):
    return [l.split(' (')[0].strip() for l in text.splitlines() if l.strip().startswith('/') and pathlib.Path(l.split(' (')[0].strip()).is_file()]


def law_used(d, plugins):
    if plugins: return any(pathlib.Path(p).stem == 'law' for p in plugins)
    s = d / 'scope.md'
    return s.exists() and bool(re.search(r'\bplugins?\b[^\n.]{0,40}\blaw\b|plugins/law\.md', s.read_text(encoding='utf-8', errors='replace'), re.I))


def verification(d):
    """Summary of DIR/state/verifier.json (written by verifier.py --state), or None when the verifier left no receipt."""
    try: v = json.loads((d / 'state' / 'verifier.json').read_text(encoding='utf-8'))
    except (OSError, ValueError): return None
    return {k: v.get(k) for k in ('summary', 'fulltext_mode', 'fulltext_cap', 'fulltext_attempted', 'fulltext_obtained', 'fulltext_not_tried_cap', 'origins', 'gateway', 'model')}


def finish(d, T=None, plugins=(), offline=False, rw_csv=None, prisma=False, followups=False, prior_art=False):
    d = pathlib.Path(d).resolve(); steps, files = [], []
    receipt = d / 'state' / 'finish_run.json'
    pre = []
    if prior_art:                                                 # the answer is written before the fingerprints: it is an input of check 13
        c0, o = _run(['prior_art.py', d]); pre.append({'step': 'prior_art', 'status': 'ok' if c0 == 0 else 'problems', 'detail': o})
        files.extend(_paths(o))
    inputs = vc.fingerprints(d)                                   # before any step: a file changed later makes this receipt stale (check 13)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'inputs': inputs, 'T': T,
                                   'plugins': list(plugins), 'offline': offline}, ensure_ascii=False, indent=1), encoding='utf-8')

    def step(name, status, detail, out=()):
        steps.append({'step': name, 'status': status, 'detail': detail}); files.extend(x for x in out if x not in files)
    steps.extend(pre)
    # 1 validate_card --header
    hdr = (d / 'state' / 'journal.jsonl').exists()
    c1, o = _run(['validate_card.py', d] + (['--header'] if hdr else []) + (['--prior-art'] if prior_art else []))
    step('validate_card' + (' --header' if hdr else ''), 'ok' if c1 == 0 else 'problems',
         ('' if hdr else 'header skipped: no state/journal.jsonl (injected mode); ') + o, [str(d / 'run.json')] if hdr and (d / 'run.json').exists() else [])
    # 2 validate_result
    if prior_art: c2 = 0; step('validate_result', 'skipped', 'prior-art mode: no result.json')
    elif (d / 'result.json').exists():
        c2, o = _run(['validate_result.py', d / 'result.json']); step('validate_result', 'ok' if c2 == 0 else 'problems', o)
    else: c2 = 1; step('validate_result', 'problems', 'result.json missing')
    # 3 retractions
    try:
        r = retractions(d, offline, rw_csv); sm = r['summary']; n = sum(sm.values())
        bad = {k: v['state'] for k, v in r['sources'].items() if v['state'] in ('retracted', 'concern', 'erratum')}
        unk = [k for k, v in r['sources'].items() if v['state'] == 'unknown']
        if not n: step('retractions', 'skipped', 'no DOI in card.json sources')
        else: step('retractions', 'problems' if bad or unk else 'ok', f'{n} DOI: ' + ', '.join(f'{k} {v}' for k, v in sm.items() if v)
                   + (f'; flagged: {bad}' if bad else '') + (f'; unknown (stays unknown): {unk}' if unk else ''), [str(d / 'retractions.json')])
    except Exception as e: step('retractions', 'problems', f'{type(e).__name__}: {e}')
    # 4 law_checks
    if law_used(d, plugins):
        a = ['law_checks.py', d] + (['--T', T] if T else []) + [x for p in plugins for x in ('--plugin', p)] + (['--no-fetch'] if offline else [])
        c4, o = _run(a)
        try: s = json.loads(o.splitlines()[-1]); st = 'problems' if s.get('to_apply') else 'ok'
        except Exception: s, st = None, 'problems'
        step('law_checks', st if c4 == 0 else 'problems', o if s is None else f"to_apply {s.get('to_apply')}, to_flag {s.get('to_flag')} (applied by the orchestrator, SKILL.md section 7)",
             [s['out']] if s and s.get('out') else [])
    else: step('law_checks', 'skipped', 'no law plugin (--plugin or scope.md)')
    # optional: PRISMA flow diagram, follow-up questions (before the exports, which append them to REPORT.html)
    for flag, name in ((prisma, 'prisma'), (followups, 'followups')):
        if flag:
            c, o = _run([f'{name}.py', d]); step(name, 'ok' if c == 0 else 'problems', o.splitlines()[-1] if o else '', _paths(o))
    # 5-6 exports
    if (d / 'REPORT.md').exists():
        xr = (['--prisma'] if prisma else []) + (['--followups'] if followups else [])
        for name, a in (('export_report', ['export_report.py', d, '--pdf', '--open'] + xr), ('export_data', ['export_data.py', d])):
            c, o = _run(a); pdf_note = [l for l in o.splitlines() if l.startswith('PDF:')]
            step(name, 'ok' if c == 0 else 'problems', (' '.join(pdf_note) or o.splitlines()[-1]) if o else '', _paths(o))
    else:
        for name in ('export_report', 'export_data'): step(name, 'skipped', 'no REPORT.md')
    out = {'dir': str(d), 'validation_passed': c1 == 0 and c2 == 0, 'steps': steps, 'files': files, 'verification': verification(d)}
    receipt.write_text(json.dumps({**json.loads(receipt.read_text(encoding='utf-8')), 'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
                                   'validation_passed': out['validation_passed'], 'steps': [{k: s[k] for k in ('step', 'status')} for s in steps],
                                   'verification': out['verification']}, ensure_ascii=False, indent=1), encoding='utf-8')
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description='End steps of a run (SKILL.md section 8 + retraction check), one summary. No model.')
    ap.add_argument('run_dir'); ap.add_argument('--T'); ap.add_argument('--plugin', action='append', default=[])
    ap.add_argument('--offline', action='store_true', help='no network: retraction check from the cache, law_checks --no-fetch')
    ap.add_argument('--rw-csv', help='Retraction Watch CSV (crossref/retraction-watch-data), optional'); ap.add_argument('--json', action='store_true')
    ap.add_argument('--prisma', action='store_true', help='optional: PRISMA 2020 flow diagram (tools/prisma.py), also in REPORT.html')
    ap.add_argument('--followups', action='store_true', help='optional: follow-up questions (tools/followups.py), also in REPORT.html')
    ap.add_argument('--prior-art', action='store_true', help='optional "Prior art?" mode: PRIOR-ART.md (tools/prior_art.py), validate_card --prior-art')
    a = ap.parse_args(argv)
    if not pathlib.Path(a.run_dir).is_dir(): print(f'not a directory: {a.run_dir}', file=sys.stderr); return 2
    if a.T and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', a.T): ap.error(f'date expected as YYYY-MM-DD: {a.T!r}')
    r = finish(a.run_dir, a.T, a.plugin, a.offline, a.rw_csv, prisma=a.prisma, followups=a.followups, prior_art=a.prior_art)
    if a.json: print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        for s in r['steps']:
            print(f"{s['step']:<24} {s['status']:<9} " + ' | '.join(x for x in str(s['detail']).splitlines()[:6] if x))
        v = r.get('verification')
        print('verification: ' + ('no state/verifier.json (tools/verifier.py verify ... --state <dir>/state not run)' if not v else
              f"{v.get('summary')}; full text {v.get('fulltext_obtained')}/{v.get('fulltext_attempted')} obtained/attempted"
              + (f", {v.get('fulltext_not_tried_cap')} beyond the cap" if v.get('fulltext_not_tried_cap') else '')
              + (f"; gateway pool {v['gateway'].get('pool')} cap {v['gateway'].get('cap')}" if v.get('gateway') else '')))
        print('validation: ' + ('passed' if r['validation_passed'] else 'FAILED (exit 1)'))
        for f in r['files']: print(f)
    return 0 if r['validation_passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
