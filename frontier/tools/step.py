#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Record one step of the idea in <dir>/run.json, with its cost and duration (SKILL.md, every step). Offline.

Each call appends {"step", "utc", "duration_s", "cost_usd"[, "vp_run"][, "note"]} to run.json (created when absent;
the file is rewritten whole through a temporary file, earlier entries unchanged). Cost and duration are what the host
reports: --cost-usd when the host gives a cost, --started-utc and --ended-utc when the step's times are known; otherwise
"unknown", never an estimate. tools/run_test.py records the "execution" step itself, with the duration it measured.
Budget per idea (config.json "budget"): at most budget.vp_runs "vp_run" steps, budget.critiques "critique" steps and
budget.executions "execution" steps; a step beyond the budget is refused (exit code 1) and not written. tools/check.py
reads run.json for the same budget ([BUDGET]) and its form ([RUNLOG]).
The extra step-8 rebound_critique batch has its own config.json rebound_critiques_max;
it does not consume the protocol critique budget.
Steps: setup, intake, vp_run (needs --vp-run NAME, the name used in intake.json vp.runs), prior_art, hypotheses, tests,
critique, execution, card, other, framing, research_plan, named (v2; the work steps vp_run, prior_art, hypotheses, tests,
critique and research_plan are refused in a v2 directory until tools/framing.py has approved, corrected or assumed the
framing), rebound (step 8 or 8-bis written), rebound_vp_run (needs --vp-run NAME: one light VP
prior-art run of a neighbouring idea; at most config.json rebound.prior_art_checks_card_max per card, both rebound
files together; they do not count in budget.vp_runs), free_draft (the hybrid free draft is sealed: its SHA-256 is
recorded; needs <dir>/free_draft.md), context, evidence, matter, moment (no budget).

Usage: step.py DIR --step NAME [--vp-run NAME] [--cost-usd X] [--started-utc U --ended-utc U] [--note TEXT]
Exit codes: 0 written, 1 refused by the budget, 2 usage error.
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ written in the skill directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import guards  # noqa: E402

STEPS = ('setup', 'intake', 'vp_run', 'prior_art', 'hypotheses', 'tests', 'critique', 'execution', 'card', 'other',
         'rebound', 'rebound_vp_run', 'history', 'free_draft', 'context', 'evidence', 'matter', 'moment', 'critique2',
         'framing', 'research_plan', 'named', 'rebound_critique')
# v2: the work steps wait for the framing (approved, corrected or assumed, tools/framing.py); SKILL.md "Frontier v2: the path"
GATED = ('vp_run', 'prior_art', 'hypotheses', 'tests', 'critique', 'research_plan')
BUDGETED = {'vp_run': 'vp_runs', 'critique': 'critiques', 'execution': 'executions'}


def cap_of(step):
    """Budget of a step: config.json budget, for "rebound_vp_run" rebound.prior_art_checks_card_max (per card), for
    "critique2" (the second critique on the corrections, round 3) config.json second_critiques_max."""
    cfg = common.config()
    if step == 'rebound_vp_run':
        return cfg['rebound']['prior_art_checks_card_max']
    if step == 'rebound_critique':
        return cfg.get('rebound_critiques_max', 0)
    if step == 'critique2':
        return cfg['second_critiques_max']
    return cfg['budget'].get(BUDGETED[step], 0)


def framing_decided(work):
    try:
        f = common.read_json(Path(work) / 'framing.json')
    except (OSError, ValueError):
        return False
    a = f.get('approval') if isinstance(f, dict) else None
    return isinstance(a, dict) and a.get('status') in ('approved', 'corrected', 'assumption')


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_utc(s):
    return datetime.datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dir')
    ap.add_argument('--step', required=True)
    ap.add_argument('--vp-run')
    ap.add_argument('--cost-usd', type=float)
    ap.add_argument('--started-utc')
    ap.add_argument('--ended-utc')
    ap.add_argument('--note')
    a = ap.parse_args(argv)
    work = Path(a.dir)

    def usage(msg):
        print('step.py: %s' % msg, file=sys.stderr)
        return 2
    if not work.is_dir():
        return usage('not a directory: %s' % work)
    if a.step not in STEPS:
        return usage('--step must be one of %s' % ', '.join(STEPS))
    if a.step in ('vp_run', 'rebound_vp_run') and not a.vp_run:
        return usage('a %s step needs --vp-run NAME (its name in intake.json vp.runs)' % a.step)
    if a.cost_usd is not None and a.cost_usd < 0:
        return usage('--cost-usd must be >= 0')
    if a.step in GATED and guards.is_v2(work) and not framing_decided(work):
        print('step.py: refused: the framing has not been approved, corrected or assumed yet (tools/framing.py): the work of '
              'step %s waits for it' % a.step, file=sys.stderr)
        return 1
    duration = 'unknown'
    try:
        if a.started_utc and a.ended_utc:
            d = (parse_utc(a.ended_utc) - parse_utc(a.started_utc)).total_seconds()
            if d < 0:
                return usage('--ended-utc is before --started-utc')
            duration = int(d) if float(d).is_integer() else d
        elif a.started_utc or a.ended_utc:
            for s in (a.started_utc, a.ended_utc):
                if s:
                    parse_utc(s)
    except ValueError:
        return usage('times are YYYY-MM-DDTHH:MM:SSZ')
    p = work / 'run.json'
    try:
        data = common.read_json(p) if p.exists() else {'steps': []}
    except ValueError as e:
        return usage('run.json is not JSON (%s); it is not repaired' % e)
    if not isinstance(data, dict) or not isinstance(data.get('steps'), list):
        return usage('run.json has no "steps" list; it is not repaired')
    if a.step in BUDGETED or a.step in ('rebound_vp_run', 'critique2', 'rebound_critique'):
        cap = cap_of(a.step)
        used = sum(1 for s in data['steps'] if isinstance(s, dict) and s.get('step') == a.step)
        if used >= cap:
            where = ('config.json rebound.prior_art_checks_card_max, per card' if a.step == 'rebound_vp_run'
                     else 'config.json rebound_critiques_max' if a.step == 'rebound_critique'
                     else 'config.json second_critiques_max' if a.step == 'critique2' else 'config.json budget.%s' % BUDGETED[a.step])
            print('step.py: refused: budget per idea reached for %s (%d of %d, %s)' % (a.step, used, cap, where),
                  file=sys.stderr)
            return 1
    extra = {}
    if a.step == 'free_draft':
        # the hybrid free draft is sealed here: its SHA-256 is recorded, tools/check.py compares it with the file
        draft = work / 'free_draft.md'
        if not draft.is_file():
            return usage('a free_draft step needs <dir>/free_draft.md (write the free draft first)')
        extra['sha256'] = common.sha256_file(draft)
    entry = {'step': a.step, 'utc': a.ended_utc or utc_now(), 'duration_s': duration,
             'cost_usd': a.cost_usd if a.cost_usd is not None else 'unknown'}
    entry.update(extra)
    if a.vp_run:
        entry['vp_run'] = a.vp_run
    if a.note:
        entry['note'] = a.note
    data['steps'].append(entry)
    common.write_json(p, data)
    print(json.dumps(entry, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
