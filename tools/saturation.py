#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Stop on saturation computed by code (SKILL.md section 4, step 5). Standard library, no model, no gateway call.

The rule is the one of SKILL.md: continue, except when two consecutive waves, each with at least the minimum number of calls fixed at
framing, brought no new eligible document, or at the ceiling. What the orchestrator used to count by hand is read from the files:
  - eligible documents: identifiers (pmid:, doi:, arxiv:) on a candidate line of searches/*.md whose verdict matches
    possibles.verdict_regex (possible / probable), the same reading as tools/read_possibles.py;
  - calls of a wave: lines of <state>/journal.jsonl of the searches' pool (no `pool` field) journaled since the previous closure.
--close-wave closes the current wave: the searches/*.md files not yet assigned and the calls journaled since the previous closure are
written to <state>/saturation.json (written by this tool only, never by hand). Without --close-wave: the decision, nothing written.

Indicator, never the rule: Chapman's capture-recapture estimate over the last two closed waves, N = (n1+1)(n2+1)/(m+1) - 1, with n1, n2
the eligible documents found by each wave (new or found again) and m those found by both. Waves are not independent samples (a
complement aims at what is missing), so it is an order of size of what remains unseen, written next to the decision.

  saturation.py --dir DIR [--state DIR/state] [--close-wave] [--min-calls N] [--cap N]

Output (stdout, JSON): decision continue | stop | ceiling, reason, waves, chapman, and `scope_line`, the line to add to scope.md after a
closure. Exit 0; 2 bad arguments (no searches/ directory, --min-calls missing at the first closure)."""
import argparse, datetime as dt, json, pathlib, re, sys
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P))
from read_possibles import ID_RE, norm, CFG   # noqa: E402  (identifier reading and verdict regex shared with read_possibles.py)


def search_files(d):
    return sorted((pathlib.Path(d) / 'searches').glob('*.md'), key=lambda p: (len(p.stem), p.stem))


def eligible(files):
    """Normalised identifiers on the candidate lines (verdict possible / probable) of the given files, in order of first appearance."""
    verdict, out = re.compile(CFG['verdict_regex'], re.I), []
    for f in files:
        for line in f.read_text(errors='replace').splitlines():
            if line.lstrip().startswith('#') or not verdict.search(line): continue
            for m in ID_RE.finditer(line):
                i = norm(m.group(1))
                if i not in out: out.append(i)
    return out


def search_calls(state):
    """Gateway calls of the searches' pool journaled in <state>/journal.jsonl (verifier, possibles and other pools left out)."""
    j, n = pathlib.Path(state) / 'journal.jsonl', 0
    if not j.exists(): return 0
    for line in j.read_text(errors='replace').splitlines():
        try: e = json.loads(line)
        except ValueError: continue
        if isinstance(e, dict) and not e.get('pool'): n += 1
    return n


def chapman(a, b):
    n1, n2, m = len(a), len(b), len(set(a) & set(b))
    return {'n1': n1, 'n2': n2, 'm': m, 'N': round((n1 + 1) * (n2 + 1) / (m + 1) - 1, 1)}


def decide(waves, min_calls, cap=None, calls_total=None):
    if cap is not None and calls_total is not None and calls_total >= cap:
        return 'ceiling', f'{calls_total} search calls journaled, ceiling {cap}'
    last = waves[-2:]
    if len(waves) >= 3 and all(w['calls'] >= min_calls and not w['new'] for w in last):   # the first wave is never a saturation wave
        return 'stop', f"waves {last[0]['wave']} and {last[1]['wave']}: no new eligible document, each with at least {min_calls} calls"
    short = [w['wave'] for w in last if not w['new'] and w['calls'] < min_calls]
    return 'continue', ('wave(s) ' + ', '.join(map(str, short)) + f' brought nothing but made fewer than {min_calls} calls: they prove no saturation'
                        if short else 'fewer than two consecutive empty waves')


def run(d, state=None, close=False, min_calls=None, cap=None):
    d = pathlib.Path(d); state = pathlib.Path(state or d / 'state')
    if not (d / 'searches').is_dir(): raise ValueError(f'no searches/ directory in {d}')
    sf = state / 'saturation.json'
    doc = json.loads(sf.read_text(encoding='utf-8')) if sf.exists() else {'min_calls': None, 'waves': []}
    if min_calls is not None: doc['min_calls'] = int(min_calls)
    if close and doc['min_calls'] is None: raise ValueError('--min-calls is required at the first closure (the minimum fixed at framing)')
    calls_now = search_calls(state)
    if close:
        assigned = {f for w in doc['waves'] for f in w['files']}
        files = [f for f in search_files(d) if f.name not in assigned]
        seen = {i for w in doc['waves'] for i in w['new']}
        found = eligible(files)
        doc['waves'].append({'wave': len(doc['waves']) + 1, 'utc': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
                             'files': [f.name for f in files], 'calls': calls_now - sum(w['calls'] for w in doc['waves']),
                             'found': found, 'new': [i for i in found if i not in seen]})
        state.mkdir(parents=True, exist_ok=True)
        sf.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding='utf-8')
    waves = doc['waves']
    decision, reason = decide(waves, doc['min_calls'] or 0, cap, calls_now) if waves else ('continue', 'no wave closed')
    w = waves[-1] if waves else None
    return {'decision': decision, 'reason': reason, 'min_calls': doc['min_calls'], 'calls_total': calls_now,
            'unassigned_calls': calls_now - sum(x['calls'] for x in waves),
            'eligible_total': len({i for x in waves for i in x['new']}),
            'waves': [{'wave': x['wave'], 'files': x['files'], 'calls': x['calls'], 'found': len(x['found']), 'new': len(x['new'])} for x in waves],
            'chapman': dict(chapman(waves[-2]['found'], waves[-1]['found']), indicator_only=True) if len(waves) >= 2 else None,
            'scope_line': f"wave {w['wave']}: {w['calls']} calls, {len(w['new'])} new eligible documents ({', '.join(w['files']) or 'no file'}); "
                          f"saturation.py: {decision}" if w else None}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', required=True); ap.add_argument('--state', default=None)
    ap.add_argument('--close-wave', action='store_true'); ap.add_argument('--min-calls', type=int, default=None)
    ap.add_argument('--cap', type=int, default=None, help='ceiling of the searches (the gateway cap); omitted = not checked here')
    a = ap.parse_args()
    try: out = run(a.dir, a.state, a.close_wave, a.min_calls, a.cap)
    except ValueError as e: print(f'saturation.py: {e}', file=sys.stderr); sys.exit(2)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
