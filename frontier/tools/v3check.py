#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Frontier V3: five small, offline checks and their rendering data.

Methodological omissions are marks in every format. Only a contradicted numeric
minimum or claimed power adds a blocking problem. No network or model calls.
"""
import datetime
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
import sim

PITFALLS = ('rule_escape_hatch', 'target_signal_circularity', 'proxy_as_target')
PRIOR_KINDS = ('paper', 'software', 'platform', 'dataset', 'other')


def obj(value):
    return value if isinstance(value, dict) else {}


def filled(value):
    return isinstance(value, str) and not common.is_placeholder(value.strip(), 1)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def tests(data):
    return [t for t in obj(data.get('tests.json')).get('tests') or [] if isinstance(t, dict)]


def mark(warnings, code, message):
    warnings.append('mark: [%s] %s' % (code, message))


def _journal_count(path):
    """Unknown on a missing or malformed journal; an empty readable journal is zero."""
    import json
    try:
        count = 0
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if not isinstance(entry, dict):
                return None
            if entry.get('call'):
                count += 1
        return count
    except (OSError, ValueError, UnicodeError):
        return None


def rebound_usage(work, data):
    """Per-neighbour calls and shares; all totals deduplicate journal content (SHA-256).

    Registered VP runs plus Frontier's research/matter journals cover the VP
    gateway calls observable from this run directory. No run.json total is used.
    """
    work = Path(work)
    runs = obj(obj(data.get('intake.json')).get('vp')).get('runs') or {}
    runs = obj(runs)
    paths = {}
    for name, value in runs.items():
        if isinstance(value, str):
            path = Path(value)
            paths[name] = ((path if path.is_absolute() else work / path) / 'state' / 'journal.jsonl').resolve()
    rows, mentioned = [], set()
    for fname in ('rebound.json', 'rebound_after.json'):
        for idea in obj(data.get(fname)).get('ideas') or []:
            if not isinstance(idea, dict):
                continue
            pa = obj(idea.get('prior_art'))
            name = pa.get('vp_run')
            if isinstance(name, str):
                rows.append({'neighbour': idea.get('id', '?'), 'file': fname, 'run': name,
                             'deepen': obj(pa.get('deepen'))})
                mentioned.add(name)
    for step in obj(data.get('run.json')).get('steps') or []:
        if isinstance(step, dict) and step.get('step') == 'rebound_vp_run':
            name = step.get('vp_run')
            if isinstance(name, str) and name not in mentioned:
                rows.append({'neighbour': name, 'file': 'run.json', 'run': name, 'deepen': {}})
                mentioned.add(name)
    # These journals are optional, unlike a registered run's journal.
    journals = set(paths.values())
    for name in ('research', 'matter'):
        path = (work / name / 'state' / 'journal.jsonl').resolve()
        if path.exists():
            journals.add(path)
    identities, counts = {}, {}
    for path in journals:
        try:
            st = path.stat()
            # Same file (hard link, symlink or repeated path) = same (device, inode). Two distinct files with
            # identical bytes are two journals and are both counted: never under-count the budget.
            identity = ('file', st.st_dev, st.st_ino)
        except OSError:
            identity = ('unavailable', str(path))
        identities[path] = identity
        if identity not in counts:
            counts[identity] = _journal_count(path)
    grouped = {}
    for row in rows:
        group = grouped.setdefault(str(row['neighbour']), {
            'neighbour': row['neighbour'], 'runs': [], 'files': [], 'deepen': {}})
        if row['run'] not in group['runs']:
            group['runs'].append(row['run'])
        if row['file'] not in group['files']:
            group['files'].append(row['file'])
        deep = row['deepen']
        if not group['deepen'] or (deep.get('selected') is True and filled(deep.get('reason'))):
            group['deepen'] = deep
    rows = list(grouped.values())
    complete = all(c is not None for c in counts.values()) and all(
        name in paths for row in rows for name in row['runs'])
    total = sum(c for c in counts.values() if c is not None)
    rebound_ids = {identities[paths[name]] for row in rows for name in row['runs'] if name in paths}
    rb_known = sum(counts[key] for key in rebound_ids if counts[key] is not None)
    rb_complete = True
    for row in rows:
        keys = {identities[paths[name]] for name in row['runs'] if name in paths}
        known = sum(counts[key] for key in keys if counts[key] is not None)
        available = all(name in paths for name in row['runs']) and all(counts[key] is not None for key in keys)
        rb_complete = rb_complete and available
        row.update(run=', '.join(row['runs']), file=', '.join(row['files']), known_calls=known,
                   calls=known if available else None,
                   share=known / total if available and complete and total else None)
    return {'rows': rows, 'total_calls': total, 'complete': complete,
            'rebound_calls': rb_known if rb_complete else None,
            'share': rb_known / total if complete and total else None}



def power_at_minimum(test):
    """Rerun at exactly the minimum useful effect, with the stored decision rule.

    Robust power is the worst noise/dependence cell at factor 1, with exactly the
    stored HAC model. Ordinary power is P(continue) at the minimum, not P(expected)
    at a favorable hypothesis effect. No natural-language number extraction.
    """
    sens = obj(test.get('sensitivity'))
    rb = obj(obj(sens.get('power')).get('robust'))
    effect = sens.get('minimum_useful_effect', rb.get('useful_effect'))
    if effect is None and number(sens.get('smallest_useful_effect')):
        effect = sens['smallest_useful_effect']
    result = {'power': None, 'effect': effect, 'basis': 'unknown', 'reason': ''}
    if not number(effect):
        result['reason'] = 'missing numeric minimum useful effect (sensitivity.minimum_useful_effect or robust.useful_effect)'
        return result
    try:
        if rb:
            rule = rb['rule']
            fresh = sim.robust(rb['design'], rb['n'], rb['sd_values'], rb['rho_values'], rb['overlap'], effect,
                               rule['continue_if_lower_above'], rule['stop_if_upper_below'], effect_factors=(1.,),
                               reps=rb['reps'], seed=rb['seed'], alpha=rb['alpha'], decision_counts=True)
            cells = [c for c in fresh['cells'] if c['effect'] == effect and c['scenario'] != 'null']
            worst = min(cells, key=lambda cell: cell['decision_counts']['continue'])
            count = worst['decision_counts']['continue']
            result.update(power=count / fresh['reps'], continue_count=count, reps=fresh['reps'], cells=cells,
                          worst_cell={'sd': worst['sd'], 'rho': worst['rho']},
                          basis='worst stored noise/dependence cell, factor 1, P(continue decision)')
        else:
            block = sens['simulation']
            rule = block['rule']
            fresh = sim.simulate(block['design'], block['n'], block.get('sd'),
                                 [('minimum', effect, 'continue'), ('null', 0., 'stop')],
                                 rule['continue_if_lower_above'], rule['stop_if_upper_below'],
                                 reps=block['reps'], seed=block['seed'], alpha=block['alpha'], base=block.get('base'))
            probability = fresh['scenarios'][0]['p_continue']
            result.update(power=probability, continue_count=round(probability * fresh['reps']), reps=fresh['reps'],
                          basis='stored ordinary simulation, P(continue)')
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError) as exc:
        result['reason'] = 'missing or unusable simulation inputs: %s' % exc
    return result


def stated_power_matches(stated, actual):
    """Compare at the decimal precision retained by JSON's numeric parser.

    0.017 represents a rounded 2/120, not an exact three-digit simulation.
    Trailing zeroes in a JSON number are unavailable after ordinary parsing.
    """
    mantissa, _, exponent = str(stated).lower().partition('e')
    decimals = len(mantissa.partition('.')[2]) - int(exponent or '0')
    # Half-up tolerance: 0.13 is a valid rounding of 1/8 = 0.125 (round() would round half to even).
    return 0 <= stated <= 1 and decimals >= 0 and abs(actual - stated) <= 0.5 * 10 ** -decimals + 1e-12


def power_label(test, show_counts=True):
    value = power_at_minimum(test)
    if value['power'] is None:
        return 'Power at minimum useful effect: unknown [POWER-INPUTS]'
    threshold = common.config()['power_min_threshold']
    suffix = '; UNDERPOWERED (<%s)' % threshold if value['power'] < threshold else ''
    # Preserve old V2 card bytes when no V3 field requests the new presentation.
    estimate = '%s/%s continue decisions' % (value['continue_count'], value['reps']) if show_counts else '%.3f' % value['power']
    return 'Power at minimum useful effect %s = %s%s' % (value['effect'], estimate, suffix)


def recommendation_note(tj, reco):
    deciding = set(obj(reco.get('justification')).get('from') or [])
    for key in ('next_step', 'tomorrow'):
        if obj(reco.get(key)).get('test'):
            deciding.add(reco[key]['test'])
    all_tests = [t for t in tj.get('tests') or [] if isinstance(t, dict)]
    ids = {t.get('id') for t in all_tests}
    if not deciding & ids:
        deciding.update((obj(tj.get('ranking')).get('order') or [])[:1])
    low = []
    for test in all_tests:
        if test.get('id') in deciding:
            power = power_at_minimum(test)['power']
            if power is not None and power < common.config()['power_min_threshold']:
                low.append(str(test.get('id')))
    return '; deciding test(s) %s UNDERPOWERED at the minimum useful effect' % ', '.join(low) if low else ''


def _location(test, where):
    prefix = 'tests.%s.' % test.get('id')
    if not isinstance(where, str) or not where.startswith(prefix):
        return None
    parts = where[len(prefix):].split('.')
    if not parts or parts[0] == 'pre_critique':
        return None
    value = test
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def pitfalls_line(tj):
    present = ['%s %s' % (t.get('id'), cls) for t in tj.get('tests') or [] if isinstance(t, dict)
               for cls in PITFALLS if obj(obj(t.get('pre_critique')).get(cls)).get('answer') == 'present']
    return 'Pitfalls present: %s' % ('; '.join(present) if present else 'none recorded (missing checks are marked)')


def prospective_lines(tj):
    return ['Prospective %s: %s; read-out: %s' % (t.get('id'), ' '.join(str(t.get('start_action') or 'missing start action [PROSPECTIVE]').split()),
                                                ' '.join(str(t.get('readout_date') or 'missing date [PROSPECTIVE]').split()))
            for t in tj.get('tests') or [] if isinstance(t, dict) and t.get('kind') == 'prospective']


def budget_lines(work, data):
    usage = rebound_usage(work, data)
    if not usage['rows']:
        return []
    def share(value):
        return 'unknown' if value is None else '%.1f%%' % (100 * value)
    lines = ['', '## Rebound gateway budget (offline journal counts)',
             'All VP gateway calls observed: %s%s; rebound: %s; share of all VP calls: %s. Cap per neighbour: %s.' % (
                 usage['total_calls'], '' if usage['complete'] else ' (partial coverage; some journals unavailable)',
                 usage['rebound_calls'] if usage['rebound_calls'] is not None else 'unknown', share(usage['share']),
                 common.config()['rebound_vp_max_calls_per_neighbour'])]
    for row in usage['rows']:
        deep = row['deepen']
        lines.append('- %s (%s, VP run %s): %s gateway calls; share of all VP calls: %s; host selected for deepening: %s; reason: %s' % (
            row['neighbour'], row['file'], row['run'], row['calls'] if row['calls'] is not None else 'unknown',
            share(row['share']), deep.get('selected') is True, deep.get('reason') or 'none recorded'))
    return lines


def run(work, data, problems, warnings):
    usage = rebound_usage(work, data)
    cap = common.config()['rebound_vp_max_calls_per_neighbour']
    for row in usage['rows']:
        count, deep = row['calls'], row['deepen']
        if count is None:
            mark(warnings, 'REBOUND-BUDGET', '%s VP run %s: gateway journal unavailable or invalid; call count and share unknown' %
                 (row['neighbour'], row['run']))
        if row['known_calls'] > cap and not (deep.get('selected') is True and filled(deep.get('reason'))):
            mark(warnings, 'REBOUND-BUDGET', '%s VP run %s: %s calls exceed cap %s without a host selection and reason for deepening' %
                 (row['neighbour'], row['run'], row['known_calls'], cap))
    pa = data.get('prior_art.json')
    if isinstance(pa, dict):
        facet = obj(pa.get('software_platform_search'))
        queries = facet.get('queries')
        searched = isinstance(queries, list) and any(filled(q) for q in queries)
        if not searched and not filled(facet.get('not_applicable')):
            mark(warnings, 'PRIOR-TOOLS', 'prior_art.json: no software/platform search facet or not applicable reason recorded')
        for entry in pa.get('closest_work') or []:
            if isinstance(entry, dict) and entry.get('kind') is not None and entry['kind'] not in PRIOR_KINDS:
                mark(warnings, 'PRIOR-TOOLS', 'closest_work kind %r: use paper, software, platform, dataset or other' % entry['kind'])
    for test in tests(data):
        tid = test.get('id', '?')
        sens = obj(test.get('sensitivity'))
        power = power_at_minimum(test)
        if power['power'] is None:
            mark(warnings, 'POWER-INPUTS', 'tests.json %s: %s; power at minimum useful effect unknown' % (tid, power['reason']))
        stated = sens.get('power_at_minimum')
        if 'power_at_minimum' in sens and not number(stated):
            mark(warnings, 'POWER-INPUTS', 'tests.json %s: optional sensitivity.power_at_minimum is not a finite number' % tid)
        elif number(stated) and power['power'] is not None and not stated_power_matches(stated, power['power']):
            problems.append('[POWER-MIN-MISMATCH] tests.json %s: stated power %r differs from recomputed power %r' %
                            (tid, stated, power['power']))
        rb_effect = obj(obj(sens.get('power')).get('robust')).get('useful_effect')
        if number(rb_effect) and number(sens.get('minimum_useful_effect')) and rb_effect != sens['minimum_useful_effect']:
            problems.append('[POWER-MIN-MISMATCH] tests.json %s: minimum useful effect %s contradicts robust input %s' %
                            (tid, sens['minimum_useful_effect'], rb_effect))
        pre = obj(test.get('pre_critique'))
        missing = []
        for cls in PITFALLS:
            item = obj(pre.get(cls))
            value = _location(test, item.get('where'))
            if (item.get('answer') not in ('present', 'absent', 'uncertain') or value is None or value == [] or value == {}
                    or (isinstance(value, str) and not filled(value))):
                missing.append(cls)
        if missing:
            mark(warnings, 'PITFALL-CHECK', 'tests.json %s: missing answer or nonempty same-test location for %s' % (tid, ', '.join(missing)))
    tj = obj(data.get('tests.json'))
    if tj:
        prospective = [t for t in tests(data) if t.get('kind') == 'prospective']
        if not prospective and not filled(tj.get('prospective_not_applicable')):
            mark(warnings, 'PROSPECTIVE', 'tests.json: consider a zero-cost long-horizon test or record prospective_not_applicable with a reason')
        for test in prospective:
            date = test.get('readout_date')
            try:
                valid = isinstance(date, str) and len(date) == 10 and datetime.date.fromisoformat(date).isoformat() == date
            except ValueError:
                valid = False
            if not filled(test.get('start_action')) or not valid:
                mark(warnings, 'PROSPECTIVE', 'tests.json %s: prospective test needs start_action and a calendar readout_date (YYYY-MM-DD)' % test.get('id'))
