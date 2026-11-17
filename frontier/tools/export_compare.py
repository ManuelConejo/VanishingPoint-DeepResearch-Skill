#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Blind comparison template for the round-3 verification (round-3 plan, adjustment A9): Frontier against the model alone,
on SEVERAL bare ideas, at EQUAL budget, judged blind for usefulness and work avoided. Standard library, offline, no model.

This tool does not run a comparison: it prepares it and computes the tallies from the judge's answers. The comparison itself
needs models and a human judge, which a build without network or model cannot provide.

  export --manifest M --out DIR --key KEY [--tolerance 0.10]
      manifest = {"ideas": [{"id": "I1", "idea": "<the bare idea>", "arms": {"frontier": {"file": "<IDEA-CARD.md>", "usd": 1.2,
      "minutes": 25}, "model_alone": {"file": "<answer of the model alone>", "usd": 1.1, "minutes": 20}}}, ...]}.
      Refuses fewer than 3 ideas, a missing or non-numeric cost, and arms whose cost (usd or minutes) differs by more than the
      tolerance: the budget must be equal. Draws a secret seed (os.urandom) per export: the order of the two arms of every
      idea (A, B) depends on it; the seed and the mapping are written only in KEY, which must lie outside DIR. Writes
      DIR/blind/<id>.A.md, <id>.B.md (text of each arm; lines that name the tool are removed) and DIR/blind/<id>.form.json
      (the questions: preferred, work avoided in minutes per arm, first action found in 2 minutes per arm, references that look
      invented per arm). Blinding is partial: the two formats differ, and the judge may guess the arm; say so in the report.
  stats --key KEY --answers A
      answers = {"I1": {"preferred": "A" | "B" | "tie", "work_avoided_minutes": {"A": n, "B": n}, "first_action_in_2min":
      {"A": true, "B": false}, "invented_references": {"A": 0, "B": 2}}, ...}. Prints, per real arm, the preferences, the mean
      work avoided, the share of ideas where the first action was found in 2 minutes and the invented references, and the
      number of ideas. Fewer than 3 judged ideas: "not concluding". No significance claim is made.
Exit codes: 0 done, 1 refused, 2 usage error.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ written in the skill directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

ARMS = ('frontier', 'model_alone')
NAMING = re.compile(r'(?i)frontier|tools/card\.py|IDEA-CARD|IDEA-REPORT|<!--')
MIN_IDEAS = 3
QUESTIONS = ['preferred: A, B or tie (the one that helps you most to decide what to do)',
             'work_avoided_minutes per arm: minutes of searching or designing that you did not have to do',
             'first_action_in_2min per arm: could you find the first gesture and its inputs in two minutes (true/false)',
             'invented_references per arm: references that look invented or that you cannot find']


def number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0


def order_of(seed_hex, idea_id):
    h = hashlib.sha256((seed_hex + ':' + idea_id).encode('utf-8')).digest()
    return ('frontier', 'model_alone') if h[0] % 2 == 0 else ('model_alone', 'frontier')


def clean(text):
    return '\n'.join(l for l in text.splitlines() if not NAMING.search(l)) + '\n'


def cmd_export(a):
    try:
        man = common.read_json(a.manifest)
        ideas = man['ideas']
    except (OSError, ValueError, KeyError, TypeError) as e:
        print('export_compare.py: manifest unreadable (%s)' % e, file=sys.stderr)
        return 2
    if len(ideas) < MIN_IDEAS:
        print('export_compare.py: refused: %d idea(s); the comparison needs at least %d bare ideas' % (len(ideas), MIN_IDEAS), file=sys.stderr)
        return 1
    out, key = Path(a.out).resolve(), Path(a.key).resolve()
    if key == out or out in key.parents:
        print('export_compare.py: refused: the key file must lie outside the export directory', file=sys.stderr)
        return 1
    seed = os.urandom(32).hex()
    mapping, budgets = {}, {}
    (out / 'blind').mkdir(parents=True, exist_ok=True)
    for it in ideas:
        iid, arms = it.get('id'), it.get('arms') or {}
        if not isinstance(iid, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', iid) or set(arms) != set(ARMS):
            print('export_compare.py: refused: every idea needs an id and exactly the arms %s' % ', '.join(ARMS), file=sys.stderr)
            return 1
        for k in ('usd', 'minutes'):
            vals = [arms[x].get(k) for x in ARMS]
            if not all(number(v) for v in vals):
                print('export_compare.py: refused: %s of %s is not recorded as a number for both arms (budget unknown)' % (k, iid), file=sys.stderr)
                return 1
            hi, lo = max(vals), min(vals)
            if hi > 0 and (hi - lo) / hi > a.tolerance:
                print('export_compare.py: refused: %s of %s differs by more than %.0f%% between the arms (%s): the budget must be equal'
                      % (k, iid, 100 * a.tolerance, vals), file=sys.stderr)
                return 1
        first, second = order_of(seed, iid)
        mapping[iid] = {'A': first, 'B': second}
        budgets[iid] = {x: {'usd': arms[x]['usd'], 'minutes': arms[x]['minutes']} for x in ARMS}
        for label, arm in (('A', first), ('B', second)):
            try:
                body = Path(arms[arm]['file']).read_text(encoding='utf-8')
            except (OSError, KeyError) as e:
                print('export_compare.py: refused: file of arm %s of %s unreadable (%s)' % (arm, iid, e), file=sys.stderr)
                return 1
            (out / 'blind' / ('%s.%s.md' % (iid, label))).write_text('# Idea: %s\n\n%s' % (it.get('idea', ''), clean(body)), encoding='utf-8')
        common.write_json(out / 'blind' / ('%s.form.json' % iid), {'idea': iid, 'questions': QUESTIONS, 'answers': {
            'preferred': None, 'work_avoided_minutes': {'A': None, 'B': None}, 'first_action_in_2min': {'A': None, 'B': None},
            'invented_references': {'A': None, 'B': None}}})
    common.write_json(key, {'seed': seed, 'mapping': mapping, 'budgets': budgets, 'tolerance': a.tolerance})
    print('%d ideas exported to %s; key in %s (keep it away from the judge)' % (len(ideas), out / 'blind', key))
    return 0


def cmd_stats(a):
    try:
        key = common.read_json(a.key)
        ans = common.read_json(a.answers)
    except (OSError, ValueError) as e:
        print('export_compare.py: unreadable (%s)' % e, file=sys.stderr)
        return 2
    tally = {x: {'preferred': 0, 'work_avoided_minutes': [], 'first_action_in_2min': [], 'invented_references': 0} for x in ARMS}
    ties, judged = 0, 0
    for iid, m in key['mapping'].items():
        r = ans.get(iid)
        if not isinstance(r, dict) or r.get('preferred') not in ('A', 'B', 'tie'):
            continue
        judged += 1
        if r['preferred'] == 'tie':
            ties += 1
        else:
            tally[m[r['preferred']]]['preferred'] += 1
        for label in ('A', 'B'):
            arm = m[label]
            for k in ('work_avoided_minutes', 'first_action_in_2min'):
                v = (r.get(k) or {}).get(label)
                if v is not None:
                    tally[arm][k].append(v)
            tally[arm]['invented_references'] += int((r.get('invented_references') or {}).get(label) or 0)
    out = {'ideas_judged': judged, 'ties': ties, 'equal_budget_tolerance': key.get('tolerance'), 'arms': {}}
    for arm, t in tally.items():
        w, f = t['work_avoided_minutes'], t['first_action_in_2min']
        out['arms'][arm] = {'preferred': t['preferred'], 'mean_work_avoided_minutes': round(sum(w) / len(w), 2) if w else None,
                            'first_action_found_share': round(sum(1 for x in f if x) / len(f), 3) if f else None,
                            'invented_references': t['invented_references']}
    out['reading'] = ('not concluding: fewer than %d judged ideas' % MIN_IDEAS) if judged < MIN_IDEAS else \
        'tallies only; no significance claim; one judge keeps their own bias; the blinding is partial (the formats differ)'
    print(json.dumps(out, indent=2))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('export')
    e.add_argument('--manifest', required=True)
    e.add_argument('--out', required=True)
    e.add_argument('--key', required=True)
    e.add_argument('--tolerance', type=float, default=0.10)
    s = sub.add_parser('stats')
    s.add_argument('--key', required=True)
    s.add_argument('--answers', required=True)
    a = ap.parse_args(argv)
    return cmd_export(a) if a.cmd == 'export' else cmd_stats(a)


if __name__ == '__main__':
    sys.exit(main())
