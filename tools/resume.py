#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Where to resume an interrupted run (SKILL.md "Resuming an interrupted run"). Standard library, no network, no model; reads, never writes.
From the files present in the working directory it names the next step and what is missing:
  frame      (section 2)  no scope.md, or scope.md without numbered angles
  search     (section 3)  fewer than 3 searches/<n>.md with gateway receipts (follow-up: config followup.min_searches)
  complete   (section 4)  the first wave is there, no REPORT.md, and scope.md records no stop (saturation, cap)
  write      (section 5)  the stop is recorded and REPORT.md is absent, or REPORT.md lacks some of the eight sections
  annex      (section 6)  REPORT.md complete, card.json or result.json missing or unreadable
  verify     (section 7)  card.json present, verdicts.json missing or unreadable
  apply      (section 7)  verdicts.json present, ABSENT / INVALID claims still listed, or the report still says the verification is in progress
  deliver    (section 8)  the end steps (finish_run.py) did not run on the current files, or the validation fails
  done                    nothing to do: the end steps ran on the current files and the validation passed (SUMMARY.md is optional: finish_run.py --summary)
A searches file without any gateway receipt is reported as incomplete (its number is not reused: the next searcher gets the next number).
The gateway counter continues: resume with the same --run and --state, the calls already spent count in the cap.
Usage: resume.py RUN_DIR [--json]      Exit 0 (2 when RUN_DIR is not a directory).
Import: state(dir) -> dict (also used by tools/progress.py)."""
import argparse, json, pathlib, re, sys
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P))
import report_lang as RL, validate_card as VC   # noqa: E402,E401

RECEIPT = re.compile(r'search-|\bread\b|citing|references|related|query', re.I)
STOP = re.compile(r'\bstop|saturat|cap (?:of \d+ )?reached|ceiling reached|plafond|arr[eê]t', re.I)
IN_PROGRESS = re.compile(r'(?:verification|vérification|verificación|prüfung)\s*:?\s*(?:in progress|en cours|en curso|läuft|in arbeit)', re.I)
SECTION = {'frame': 2, 'search': 3, 'complete': 4, 'write': 5, 'annex': 6, 'verify': 7, 'apply': 7, 'deliver': 8, 'done': None}


def _text(p):
    try: return pathlib.Path(p).read_text(encoding='utf-8', errors='replace')
    except OSError: return ''


def _json(p):
    try: return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError): return None


def angles(scope):
    m = re.search(r'^#{1,3}\s*Angles?\b[^\n]*\n(.*?)(?=^#{1,3}\s|\Z)', scope, re.M | re.S)
    return re.findall(r'^\s*(\d{1,2})[.)]\s+\S', m.group(1), re.M) if m else []


def waves(scope):
    m = re.search(r'^#{1,3}\s*(?:Waves?|Budget\s*/\s*waves)\b[^\n]*\n(.*?)(?=^#{1,3}\s|\Z)', scope, re.M | re.S | re.I)
    body = m.group(1) if m else ''
    return [l.strip() for l in body.splitlines() if re.match(r'^\s*[-*]?\s*wave\b', l, re.I)]


def journal(d):
    out = []
    for l in _text(d / 'state' / 'journal.jsonl').splitlines():
        try: out.append(json.loads(l))
        except ValueError: pass
    return out


def plugins_of(d, scope):
    names = sorted(p.stem for p in (P.parent / 'plugins').glob('*.md') if not p.stem.startswith('_'))
    fin = _json(d / 'state' / 'finish_run.json') or {}
    if fin.get('plugins'): return [pathlib.Path(x).stem for x in fin['plugins']]
    head = '\n'.join(scope.splitlines()[:15])
    return [n for n in names if re.search(r'(?<![\w-])' + re.escape(n) + r'(?![\w-])', head)]


def state(folder):
    d = pathlib.Path(folder).resolve()
    scope = _text(d / 'scope.md'); J = journal(d)
    search_calls = [l for l in J if (l.get('pool') or 'search') == 'search']
    run = sorted({l.get('run') for l in J if l.get('run')})
    T = sorted({l.get('T') for l in J if l.get('T')})
    if not T and (m := re.search(r'\bT\s*=\s*(\d{4}-\d{2}-\d{2})', scope)): T = [m.group(1)]
    files = sorted((d / 'searches').glob('*.md'), key=lambda p: (not p.stem.isdigit(), int(p.stem) if p.stem.isdigit() else 0, p.name)) if (d / 'searches').is_dir() else []
    good = [p.name for p in files if RECEIPT.search(_text(p))]
    incomplete = [p.name for p in files if p.name not in good]
    nums = [int(p.stem) for p in files if p.stem.isdigit()]
    report = _text(d / 'REPORT.md')
    titles = [RL.canonical(t) for t, _ in RL.raw_sections(report)]
    missing_sections = [s for s in RL.EN if s not in titles] if report else list(RL.EN)
    findings = len(RL.finding_re().findall(RL.section(report, 'Main Analysis'))) if report else 0
    card, result, ver = _json(d / 'card.json'), _json(d / 'result.json'), _json(d / 'verdicts.json')
    claims = len(card.get('claims') or []) if isinstance(card, dict) else None
    counts = {}
    for c in (ver.get('claims') or []) if isinstance(ver, dict) else []:
        if isinstance(c, dict): counts[str(c.get('status'))] = counts.get(str(c.get('status')), 0) + 1
    unhandled = [c.get('id') for c in (ver.get('claims') or []) if isinstance(c, dict) and c.get('status') in VC.UNHANDLED] if isinstance(ver, dict) else []
    fu = VC.is_followup(d); need = int(VC.FOLLOWUP.get('min_searches', 1)) if fu else 3
    wv = waves(scope)
    s = {'dir': str(d), 'followup': fu, 'language': RL.of_run(d), 'T': T[-1] if T else None, 'run': run[-1] if run else None,
         'plugins': plugins_of(d, scope), 'scope': bool(scope), 'angles': len(angles(scope)), 'waves': wv,
         'stopped': any(STOP.search(w) for w in wv), 'searches': [p.name for p in files], 'searches_with_receipts': good,
         'searches_incomplete': incomplete, 'next_search_number': max(nums) + 1 if nums else 1, 'searches_needed': need,
         'calls': len(J), 'search_calls': len(search_calls), 'verifier_calls': len(J) - len(search_calls),
         'ids_seen': len({i for l in J for i in (l.get('ids') or []) if i}),
         'counter': _text(d / 'state' / f'counter-{run[-1]}.txt').strip() if run else '',
         'report': bool(report), 'missing_sections': missing_sections if report else None, 'findings': findings,
         'in_progress': bool(IN_PROGRESS.search(report)), 'card': isinstance(card, dict), 'claims': claims,
         'result': isinstance(result, dict), 'verdicts': isinstance(ver, dict), 'counts': counts, 'unhandled': unhandled,
         'summary': (d / 'SUMMARY.md').is_file()}
    missing = []
    if not scope or not s['angles']:
        step = 'frame'; missing.append('scope.md' if not scope else 'scope.md: numbered angles (## Angles)')
    elif len(good) < need and not report:
        step = 'search'; missing.append(f'searches/: {len(good)} file(s) with receipts, {need} needed')
    elif not report:
        step = 'write' if s['stopped'] else 'complete'
        if not s['stopped']: missing.append('scope.md: no stop recorded (two waves without a new eligible document, or the cap)')
    elif missing_sections:
        step = 'write'; missing.append('REPORT.md sections: ' + ', '.join(missing_sections))
    elif not s['card'] or not s['result']:
        step = 'annex'; missing += [f for f, ok in (('card.json', s['card']), ('result.json', s['result'])) if not ok]
    elif not s['verdicts']:
        step = 'verify'; missing.append('verdicts.json')
    elif unhandled or s['in_progress']:
        step = 'apply'
        if unhandled: missing.append('ABSENT/INVALID to remove: ' + ', '.join(map(str, unhandled)))
        if s['in_progress']: missing.append('REPORT.md: the verification block still says "in progress"')
    else:
        fin = _json(d / 'state' / 'finish_run.json')
        pb = VC.end_problems(d) if (d / 'state' / 'journal.jsonl').exists() else ([] if isinstance(fin, dict) else ['state/finish_run.json (tools/finish_run.py not run)'])
        fin = fin if isinstance(fin, dict) else {}
        if pb or fin.get('validation_passed') is False:
            step = 'deliver'; missing += pb or ['validation failed at the last finish_run.py']
        else: step = 'done'
    if incomplete: missing.append('searches without any gateway receipt (relaunch under a new number): ' + ', '.join(incomplete))
    s.update(step=step, section=SECTION[step], missing=missing)
    return s


ACTION = {
    'frame': 'frame the question: write scope.md (criteria, 5 to 10 numbered angles, budget, provisional plan)',
    'search': 'launch the missing searchers of the first wave, numbered from {next}',
    'complete': 'continue section 4: deduplicate, read, triangulate, then complementary waves until two waves bring nothing new (or the cap); one line per wave in scope.md',
    'write': 'write REPORT.md (section 5), from the searches/ files',
    'annex': 'run the annex call (section 6): card.json and result.json from REPORT.md, then validate_card.py',
    'verify': 'run the verifier (section 7): tools/verifier.py verify --card card.json --out verdicts.json ...',
    'apply': 'apply the verdicts (section 7): correct the DISTORTED, remove the ABSENT / INVALID, write the verification block',
    'deliver': 'run tools/finish_run.py on the directory (section 8), then deliver as section 8 says',
    'done': 'nothing to resume: deliver as section 8 says (REPORT.md, REPORT.html)',
}


def render(s):
    L = [f"Run: {s['dir']}" + (' (follow-up)' if s['followup'] else ''),
         f"T = {s['T'] or 'unknown'}; plugins: {', '.join(s['plugins']) or 'unknown'}; gateway run name: {s['run'] or 'none yet'}; language: {s['language']}"]
    have = []
    if s['scope']: have.append(f"scope.md ({s['angles']} angles, {len(s['waves'])} wave line(s){', stop recorded' if s['stopped'] else ''})")
    if s['searches']: have.append(f"searches/ {len(s['searches'])} file(s) ({len(s['searches_with_receipts'])} with receipts)")
    if s['calls']: have.append(f"journal: {s['search_calls']} search call(s), {s['verifier_calls']} verifier call(s), {s['ids_seen']} documents seen")
    if s['report']: have.append(f"REPORT.md ({8 - len(s['missing_sections'])}/8 sections, {s['findings']} finding(s))")
    if s['card']: have.append(f"card.json ({s['claims']} claims)")
    if s['result']: have.append('result.json')
    if s['verdicts']: have.append('verdicts.json (' + ', '.join(f'{k} {v}' for k, v in s['counts'].items()) + ')')
    if s['summary']: have.append('SUMMARY.md')
    L.append('Present: ' + ('; '.join(have) if have else 'nothing'))
    act = ACTION[s['step']].format(next=s['next_search_number'])
    if s['followup']: act = act.replace('5 to 10 numbered angles, budget, provisional plan', '1 to 3 numbered angles; SKILL.md "Follow-up in the conversation"')
    L.append(f"Resume at: {s['step']}" + (f" (SKILL.md section {s['section']})" if s['section'] else '') + ' - ' + act)
    if s['missing']: L.append('Missing: ' + '; '.join(s['missing']))
    if s['run']:
        L.append(f"Keep the same gateway --run {s['run']} --state {s['dir']}/state: the counter continues"
                 + (f" ({s['counter']} search calls already counted)" if s['counter'] else ''))
    return '\n'.join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Where to resume an interrupted run (reads the files, writes nothing).')
    ap.add_argument('run_dir'); ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    if not pathlib.Path(a.run_dir).is_dir(): print(f'resume.py: not a directory: {a.run_dir!r}', file=sys.stderr); return 2
    s = state(a.run_dir)
    print(json.dumps(s, ensure_ascii=False, indent=1) if a.json else render(s))
    return 0


if __name__ == '__main__':
    sys.exit(main())
