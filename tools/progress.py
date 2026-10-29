#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""One short progress line for the user (SKILL.md section 0 "Progress"), in the language of the run. Standard library, no network, no model.
Reads the run's files (scope.md, searches/, state/journal.jsonl, REPORT.md, card.json, verdicts.json, SUMMARY.md) through
tools/resume.py state() and renders the step reached: framing (number of angles, T); searches (searcher files, gateway calls and new
documents since the previous progress line, totals); writing (findings written); annex; verification (claims); end (the answer line).
The counts "since the previous line" come from state/progress.json, which this tool alone writes (last totals seen); --no-save leaves it.
Usage: progress.py RUN_DIR [--lang CODE] [--json] [--no-save]      Exit 0 (2 when RUN_DIR is not a directory).
Import: line(dir, lang=None, save=True) -> str."""
import argparse, json, pathlib, sys
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P))
import report_lang as RL, resume as R   # noqa: E402,E401


def _ids(d):
    return {i for l in R.journal(d) if (l.get('pool') or 'search') == 'search' for i in (l.get('ids') or []) if i}


def line(folder, lang=None, save=True):
    d = pathlib.Path(folder).resolve(); s = R.state(d)
    lang = lang if lang in RL.LANGS else s['language']
    M = lambda key_, **kw: RL.msg(lang, key_, **kw)
    sp = d / 'state' / 'progress.json'
    try: last = json.loads(sp.read_text(encoding='utf-8'))
    except (OSError, ValueError): last = {}
    ids = _ids(d); calls = s['search_calls']
    new_ids = len(ids - set(last.get('ids') or [])); new_calls = max(0, calls - int(last.get('calls') or 0))
    step = s['step']
    if step == 'frame': text = M('framing_none')
    elif step == 'search' and not s['searches'] and not calls: text = M('framing', angles=s['angles'], T=s['T'] or '?')
    elif step in ('search', 'complete') or (step == 'write' and not s['report']):
        text = M('wave', files=len(s['searches']), calls=new_calls, new=new_ids, total_calls=calls, total_ids=len(ids))
    elif step == 'write': text = M('writing', findings=s['findings'])
    elif step == 'annex': text = M('annex')
    elif step == 'verify': text = M('verifying', claims=s['claims'] or 0)
    elif step in ('apply', 'deliver'):
        text = M('verified', claims=sum(s['counts'].values()), counts=', '.join(f'{k} {v}' for k, v in s['counts'].items()))
    else:
        summ = (d / 'SUMMARY.md').read_text(encoding='utf-8', errors='replace').splitlines() if s['summary'] else []
        rep = next((l for l in summ if l.startswith('**' + M('report'))), '')
        if not rep and (d / 'REPORT.html').is_file(): rep = M('report') + M('colon') + str((d / 'REPORT.html').resolve())   # SUMMARY.md is optional (--summary)
        text = M('finished', summary=rep.replace('**', ''))
    if save and (d / 'state').is_dir():
        try: sp.write_text(json.dumps({'calls': calls, 'ids': sorted(ids), 'step': step}, ensure_ascii=False) + '\n', encoding='utf-8')
        except OSError: pass
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description='One progress line for the user (no model).')
    ap.add_argument('run_dir'); ap.add_argument('--lang'); ap.add_argument('--json', action='store_true'); ap.add_argument('--no-save', action='store_true')
    a = ap.parse_args(argv)
    if not pathlib.Path(a.run_dir).is_dir(): print(f'progress.py: not a directory: {a.run_dir!r}', file=sys.stderr); return 2
    t = line(a.run_dir, a.lang, not a.no_save)
    print(json.dumps({'line': t}, ensure_ascii=False) if a.json else t)
    return 0


if __name__ == '__main__':
    sys.exit(main())
