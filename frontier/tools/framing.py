#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The approved framing of Frontier v2 (SKILL.md "Frontier v2: the path", stage 1). Offline, standard library.

After the free phase the agent restates, in four fields, what it understood: the objective, the success criterion, the
constraints and what would refute the idea. The user approves or corrects it in ONE reply; no work of stages 2 to 6 starts
before (tools/step.py refuses them in a v2 directory). When the user is absent the agent assumes the framing and the file
says so ("ASSUMED"); an assumed framing is never shown as approved. The proposal carries its SHA-256: a proposal changed
after the decision is refused by tools/check.py ([FRAMING]).

Subcommands (DIR = the working directory):
  propose DIR --objective T --success T --constraint T [--constraint T ...] --refuted-by T [--refuted-by T ...]
              [--no-free-draft REASON]
      Writes framing.json. The free phase comes first: free_draft.md must exist and its "free_draft" step be recorded
      (tools/step.py), unless --no-free-draft gives the reason, which is kept and shown. Every field is required; a
      placeholder (n/a, tbd, none ...) is refused. archives.checked says whether project folders were given
      (intake.json project_dirs): without them "not checked", no penalty.
  approve DIR --reply TEXT      The user approves: the final framing is the proposal, word for word; the reply is kept.
  correct DIR --reply TEXT [--objective T] [--success T] [--constraint T ...] [--refuted-by T ...]
                                The user corrects: the fields that change are listed by the tool, the reply is kept.
  assume DIR [--reason TEXT]    The user is absent: the framing is an assumption, marked as such.
  show DIR                      Prints framing.json.
Usage: framing.py propose|approve|correct|assume|show DIR ...
Exit codes: 0 done, 1 refused, 2 usage error.
"""
import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ written in the skill directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

FIELDS = ('objective', 'success_criterion', 'constraints', 'refuted_by')
MIN_CHARS = 12


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def proposal_sha(proposal):
    return hashlib.sha256(json.dumps(proposal, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def field_problems(p):
    """Why a framing (the four fields) is not acceptable, as a list of messages."""
    out = []
    for k in ('objective', 'success_criterion'):
        if common.is_placeholder(p.get(k), MIN_CHARS):
            out.append('%s is empty, a placeholder or shorter than %d characters' % (k, MIN_CHARS))
    for k in ('constraints', 'refuted_by'):
        items = p.get(k)
        if not isinstance(items, list) or not items:
            out.append('%s needs at least one item' % k)
        else:
            for x in items:
                if common.is_placeholder(x, MIN_CHARS):
                    out.append('%s holds an empty, placeholder or too short item (%d characters or more)' % (k, MIN_CHARS))
    return out


def load(work):
    p = Path(work) / 'framing.json'
    return common.read_json(p) if p.is_file() else None


def project_dirs_given(work):
    try:
        it = common.read_json(Path(work) / 'intake.json')
    except (OSError, ValueError):
        return False
    d = it.get('project_dirs') if isinstance(it, dict) else None
    return isinstance(d, list) and any(isinstance(x, str) and x.strip() for x in d)


def free_phase_done(work):
    work = Path(work)
    if not (work / 'free_draft.md').is_file():
        return False
    try:
        steps = common.read_json(work / 'run.json').get('steps') or []
    except (OSError, ValueError, AttributeError):
        return False
    return any(isinstance(s, dict) and s.get('step') == 'free_draft' for s in steps)


def refuse(msg):
    print('framing.py: refused: %s' % msg, file=sys.stderr)
    return 1


def cmd_propose(a):
    work = Path(a.dir)
    old = load(work)
    if old is not None and old.get('approval'):
        return refuse('the framing was already decided (%s); it is not rewritten' % old['approval'].get('status'))
    if a.no_free_draft:
        free = {'skipped': a.no_free_draft}
    elif free_phase_done(work):
        free = {'draft': 'free_draft.md'}
    else:
        return refuse('the free phase comes first: write free_draft.md and record it with tools/step.py --step free_draft '
                      '(or give --no-free-draft REASON when the user asked for no free draft)')
    p = {'objective': (a.objective or '').strip(), 'success_criterion': (a.success or '').strip(),
         'constraints': [c.strip() for c in a.constraint or []], 'refuted_by': [c.strip() for c in a.refuted_by or []]}
    probs = field_problems(p)
    if probs:
        return refuse('; '.join(probs))
    dirs = project_dirs_given(work)
    f = {'version': 1, 'proposal': p, 'proposal_sha256': proposal_sha(p), 'proposed_utc': utc_now(), 'free_phase': free,
         'archives': {'checked': dirs, 'note': ('project folders were given: tools/history.py reads them (step 0-bis)' if dirs
                                                else 'not checked (no project_dirs given): nothing is penalised')},
         'approval': None, 'final': None}
    common.write_json(work / 'framing.json', f)
    print(json.dumps(f, ensure_ascii=False, indent=2))
    return 0


def pending(a):
    f = load(a.dir)
    if f is None:
        print('framing.py: no framing.json: run propose first', file=sys.stderr)
        return None, 1
    if f.get('approval'):
        return None, refuse('the framing was already decided (%s)' % f['approval'].get('status'))
    return f, 0


def decide(work, f, status, by, reply, final, changes=None):
    a = {'status': status, 'by': by, 'reply': reply, 'utc': utc_now()}
    if changes is not None:
        a['changes'] = changes
    f['approval'] = a
    f['final'] = final
    common.write_json(Path(work) / 'framing.json', f)
    print(json.dumps({'status': status, 'by': by, 'changes': changes, 'final': final}, ensure_ascii=False, indent=2))
    return 0


def cmd_approve(a):
    f, rc = pending(a)
    if f is None:
        return rc
    if len((a.reply or '').strip()) < 3:
        return refuse('the user\'s reply is required and is kept word for word')
    return decide(a.dir, f, 'approved', 'user', a.reply.strip(), json.loads(json.dumps(f['proposal'])), [])


def cmd_correct(a):
    f, rc = pending(a)
    if f is None:
        return rc
    if len((a.reply or '').strip()) < 3:
        return refuse('the user\'s reply is required and is kept word for word')
    final = json.loads(json.dumps(f['proposal']))
    if a.objective:
        final['objective'] = a.objective.strip()
    if a.success:
        final['success_criterion'] = a.success.strip()
    if a.constraint:
        final['constraints'] = [c.strip() for c in a.constraint]
    if a.refuted_by:
        final['refuted_by'] = [c.strip() for c in a.refuted_by]
    changes = [k for k in FIELDS if final[k] != f['proposal'][k]]
    if not changes:
        return refuse('a correction that changes no field is an approval (use approve)')
    probs = field_problems(final)
    if probs:
        return refuse('; '.join(probs))
    return decide(a.dir, f, 'corrected', 'user', a.reply.strip(), final, changes)


def cmd_assume(a):
    f, rc = pending(a)
    if f is None:
        return rc
    why = (a.reason or 'the user was not there to answer').strip()
    return decide(a.dir, f, 'assumption', 'assumption', 'ASSUMED: %s; this framing was not approved by anyone.' % why,
                  json.loads(json.dumps(f['proposal'])), [])


def cmd_show(a):
    f = load(a.dir)
    if f is None:
        print('framing.py: no framing.json', file=sys.stderr)
        return 1
    print(json.dumps(f, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog='Usage: framing.py propose|approve|correct|assume|show DIR ...')
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('propose', 'approve', 'correct', 'assume', 'show'):
        s = sub.add_parser(name)
        s.add_argument('dir')
        if name in ('propose', 'correct'):
            s.add_argument('--objective')
            s.add_argument('--success')
            s.add_argument('--constraint', action='append')
            s.add_argument('--refuted-by', dest='refuted_by', action='append')
        if name == 'propose':
            s.add_argument('--no-free-draft', dest='no_free_draft')
        if name in ('approve', 'correct'):
            s.add_argument('--reply', required=True)
        if name == 'assume':
            s.add_argument('--reason')
    a = ap.parse_args(argv)
    return {'propose': cmd_propose, 'approve': cmd_approve, 'correct': cmd_correct, 'assume': cmd_assume, 'show': cmd_show}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
