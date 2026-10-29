#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""One short progress line for the user (SKILL.md section 0 "Progress"), in the language of the run. Standard library, no network, no model.
Reads the run's files (scope.md, searches/, state/journal.jsonl, REPORT.md, card.json, verdicts.json, SUMMARY.md) through
tools/resume.py state() and renders the step reached: framing (number of angles, T); searches (searcher files, gateway calls and new
documents since the previous progress line, totals); writing (findings written); annex; verification (claims); end (the answer line).
The counts "since the previous line" come from state/progress.json, which this tool alone writes (last totals seen); --no-save leaves it.
Usage: progress.py RUN_DIR [--lang CODE] [--json] [--no-save]      Exit 0 (2 when RUN_DIR is not a directory).
       progress.py --hook   (Claude Code PostToolUse hook of the SKILL.md header; never run by the model): reads the hook event on stdin,
       finds the run directory from the paths of the tool call (the nearest directory holding scope.md), and, when the run reached a
       later step (or a new searcher file during the searches), prints {"systemMessage": "<line>"} so that the host shows the line to
       the user, and appends it to state/progress.log. Nothing otherwise; always exit 0, never blocks a tool call.
Settings: tools/config.json `progress` (tools the hook reacts to, log file name, steps in order).
Import: line(dir, lang=None, save=True) -> str; hook(event: dict) -> str | None (the line shown, if any)."""
import argparse, datetime as dt, json, pathlib, shlex, sys
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P))
import report_lang as RL, resume as R   # noqa: E402,E401

CFG = json.loads((P / 'config.json').read_text(encoding='utf-8')).get('progress') or {}


def _ids(d):
    return {i for l in R.journal(d) if (l.get('pool') or 'search') == 'search' for i in (l.get('ids') or []) if i}


def _render(folder, lang=None):
    """(kind, text, state, totals) of the step reached; writes nothing."""
    d = pathlib.Path(folder).resolve(); s = R.state(d)
    lang = lang if lang in RL.LANGS else s['language']
    M = lambda key_, **kw: RL.msg(lang, key_, **kw)
    sp = d / 'state' / 'progress.json'
    try: last = json.loads(sp.read_text(encoding='utf-8'))
    except (OSError, ValueError): last = {}
    ids = _ids(d); calls = s['search_calls']
    new_ids = len(ids - set(last.get('ids') or [])); new_calls = max(0, calls - int(last.get('calls') or 0))
    step = s['step']
    kind = step
    if step == 'frame': text = M('framing_none')
    elif step == 'search' and not s['searches'] and not calls: kind, text = 'framing', M('framing', angles=s['angles'], T=s['T'] or '?')
    elif step in ('search', 'complete') or (step == 'write' and not s['report']):
        kind = 'searches'; text = M('wave', files=len(s['searches']), calls=new_calls, new=new_ids, total_calls=calls, total_ids=len(ids))
    elif step == 'write': kind, text = 'writing', M('writing', findings=s['findings'])
    elif step == 'annex': text = M('annex')
    elif step == 'verify': text = M('verifying', claims=s['claims'] or 0)
    elif step in ('apply', 'deliver'):
        kind = 'verified'; text = M('verified', claims=sum(s['counts'].values()), counts=', '.join(f'{k} {v}' for k, v in s['counts'].items()))
    else:
        summ = (d / 'SUMMARY.md').read_text(encoding='utf-8', errors='replace').splitlines() if s['summary'] else []
        rep = next((l for l in summ if l.startswith('**' + M('report'))), '')
        if not rep and (d / 'REPORT.html').is_file(): rep = M('report') + M('colon') + str((d / 'REPORT.html').resolve())   # SUMMARY.md is optional (--summary)
        text = M('finished', summary=rep.replace('**', ''))
    return kind, text, s, {'calls': calls, 'ids': sorted(ids), 'step': step}


def _last(d):
    try: x = json.loads((d / 'state' / 'progress.json').read_text(encoding='utf-8'))
    except (OSError, ValueError): x = {}
    return x if isinstance(x, dict) else {}


def _save(d, totals, **extra):
    if not (d / 'state').is_dir(): return
    x = _last(d); x.update(totals); x.update(extra)
    try: (d / 'state' / 'progress.json').write_text(json.dumps(x, ensure_ascii=False) + '\n', encoding='utf-8')
    except OSError: pass


def line(folder, lang=None, save=True):
    d = pathlib.Path(folder).resolve(); kind, text, s, totals = _render(d, lang)
    if save: _save(d, totals)
    return text


def _paths(event):
    ti = event.get('tool_input') if isinstance(event.get('tool_input'), dict) else {}
    out = [ti[k] for k in ('file_path', 'path', 'notebook_path') if isinstance(ti.get(k), str)]
    if isinstance(ti.get('command'), str):
        try: words = shlex.split(ti['command'])
        except ValueError: words = ti['command'].split()
        for w in words: out += [w] + ([w.split('=', 1)[1]] if w.startswith('--') and '=' in w else [])
    return out


def run_dir(event):
    """The nearest directory holding scope.md above one of the paths of the tool call (relative paths from the event's cwd)."""
    cwd = pathlib.Path(event.get('cwd') or '.')
    for raw in _paths(event):
        if not raw or raw.startswith('-'): continue
        p = pathlib.Path(raw); p = p if p.is_absolute() else cwd / p
        try: p = p.resolve()
        except (OSError, RuntimeError): continue
        for c in ([p] if p.is_dir() else []) + list(p.parents):
            if (c / 'scope.md').is_file(): return c
    return None


def hook(event):
    """Claude Code PostToolUse: the progress line to show, or None. Shows a step once, in order (config `progress.steps`);
    during the searches, from the first searcher file, again when a new one appears. Never raises."""
    try:
        if not isinstance(event, dict) or event.get('agent_id') or event.get('tool_name') not in (CFG.get('hook_tools') or []): return None
        d = run_dir(event)
        if d is None or not (d / 'state').is_dir(): return None
        kind, text, s, totals = _render(d)
        steps = CFG.get('steps') or []
        if kind not in steps: return None
        last = _last(d); rank, prev = steps.index(kind), last.get('hook_step')
        prev_rank = steps.index(prev) if prev in steps else -1
        files = len(s['searches'])
        if kind == 'searches' and not files: return None   # calls under way, no searcher file yet: wait for the first one
        if rank < prev_rank or (rank == prev_rank and not (kind == 'searches' and files > int(last.get('hook_files') or 0))): return None
        _save(d, totals, hook_step=kind, hook_files=files)
        try:
            with open(d / 'state' / (CFG.get('log') or 'progress.log'), 'a', encoding='utf-8') as f:
                f.write(json.dumps({'utc': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'step': kind,
                                    'tool': event.get('tool_name'), 'line': text}, ensure_ascii=False) + '\n')
        except OSError: pass
        return text
    except Exception:   # a hook never breaks the run
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description='One progress line for the user (no model).')
    if argv is None: argv = sys.argv[1:]
    if argv[:1] == ['--hook']:
        try: ev = json.loads(sys.stdin.read() or '{}')
        except (ValueError, OSError): ev = {}
        t = hook(ev)
        if t: print(json.dumps({'systemMessage': t}, ensure_ascii=False))
        return 0
    ap.add_argument('run_dir'); ap.add_argument('--lang'); ap.add_argument('--json', action='store_true'); ap.add_argument('--no-save', action='store_true')
    a = ap.parse_args(argv)
    if not pathlib.Path(a.run_dir).is_dir(): print(f'progress.py: not a directory: {a.run_dir!r}', file=sys.stderr); return 2
    t = line(a.run_dir, a.lang, not a.no_save)
    print(json.dumps({'line': t}, ensure_ascii=False) if a.json else t)
    return 0


if __name__ == '__main__':
    sys.exit(main())
