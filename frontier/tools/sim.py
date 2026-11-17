#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Simple sensitivity simulation for a Frontier test (SKILL.md step 3). Standard library, fixed seed, no network.

Question answered: with this design, effect, noise and n, how often does the decision rule fixed in advance give each
decision under each competing scenario, and does it give the expected one often enough to tell the scenarios apart?

Designs (n = per arm, or number of pairs):
  means        two arms, normal outcomes with standard deviation --sd; estimate = mean(B) - mean(A), Welch standard error
  proportions  two arms, Bernoulli outcomes, arm A rate --base, arm B rate base + effect; estimate = difference of rates
  paired       n paired differences, normal with standard deviation --sd; estimate = mean difference
Each scenario fixes the true effect (B - A, or the mean paired difference): --scenario NAME=EFFECT (two at least, one per
competing hypothesis), and the decision the rule should give under it: --expect NAME=continue|revise|stop|indeterminate.

Decision rule simulated (the structured core of decision_rule in tests.json), on the (1 - alpha) normal confidence interval:
  continue       lower bound > --continue-if-lower-above and not (upper bound < --stop-if-upper-below)
  stop           upper bound < --stop-if-upper-below and not (lower bound > --continue-if-lower-above)
  revise         both (a real effect, but smaller than the useful one)
  indeterminate  neither
Output (stdout, JSON): the parameters, per scenario p_continue / p_revise / p_stop / p_indeterminate and p_expected, then
"distinguishes" = every scenario with an expectation reaches p_expected >= --threshold (default 0.8) and at least two
scenarios expect different decisions; "min_p_expected" the lowest of them. The output is meant to be copied as is into
tests.json, sensitivity.simulation: --write-into <dir>/tests.json --test T1 does it, and also writes the two thresholds
into decision_rule.thresholds; when that test already has decision_rule.thresholds, they are the ones simulated (other
values given on the command line are refused). Scenario names are the competing hypotheses of the test, and each effect
lies in the interval its hypothesis predicts (tools/check.py [SIM-LINK]); tools/check.py reruns the simulation from the
stored parameters and refuses any difference ([SIM-RERUN]).

Project context (SKILL.md step 0-quater). With --context DIR, n, sd and base that the command line does not give are read in
the CONFIRMED key numbers of DIR/intake.json context (role n, sd or base, else the usual names n_periods, n_units, sd,
base_rate ...). The output always carries a "context" block: "used" (true when at least one parameter came from the
context), "inputs" (parameter -> name, value, cited, source), "not_from_context" (what was given by hand), "missing" (what
the context lacks), "differs" (a command-line value that differs from the context number: the command line wins, the gap is
written) and "note". Without --context, or when the context lacks the number, the note says so: the power is then not
tied to the project's real numbers. tools/check.py rechecks a simulation that says it used the context ([CONTEXT-SIM]).

Test size needed (SKILL.md step 2-bis). --needed-n --effect E [--power 0.8] [--alpha 0.05] with --design and --sd (or --base):
the size per arm (means, proportions) or the number of pairs (paired) that detects the effect E (the lower bound of the
(1 - alpha) interval above 0) with the given power. First the normal-approximation formula, then a simulation check with the
fixed seed (n grows by 10% until the simulated power is within 0.02 of the target). The block is deterministic and
tools/check.py reruns it ([EVID-SIZE]). --write-into <evidence_table.json> --entry E1 stores it in that entry.

Usage: sim.py --design means|proportions|paired --n N [--sd SD] [--base P] --scenario H1=0.5 --scenario R1=0
              [--expect H1=continue --expect R1=stop] --continue-if-lower-above X --stop-if-upper-below Y
              [--alpha 0.05] [--reps 2000] [--seed 20261114] [--threshold 0.8] [--write-into tests.json --test T1]
              [--context DIR]
       sim.py --design means|proportions|paired --needed-n --effect E [--sd SD] [--base P] [--power 0.8] [--alpha 0.05]
              [--context DIR] [--write-into evidence_table.json --entry E1]
Import: simulate(design, n, sd, scenarios=[(name, effect, expected or None)], continue_if_lower_above,
        stop_if_upper_below, reps=2000, seed=20261114, alpha=0.05, base=None, threshold=0.8) -> dict
        needed_n(design, effect, sd=None, base=None, alpha=0.05, power=0.8, reps=2000, seed=20261114) -> dict,
        rerun_needed_n(block), compare_needed_n(stored, fresh), context_block(intake, cli, needed)
"""
import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

DECISIONS = ('continue', 'revise', 'stop', 'indeterminate')
MAX_DRAWS = 20000000


def _decide(lo, hi, c, s):
    cont = lo > c
    stop = hi < s
    if cont and stop:
        return 'revise'
    if cont:
        return 'continue'
    if stop:
        return 'stop'
    return 'indeterminate'


def _sample_var(rng, sd, n):
    # sample variance of n normal draws with standard deviation sd: sd^2 * chi2(n-1) / (n-1)
    return sd * sd * rng.gammavariate((n - 1) / 2.0, 2.0) / (n - 1)


def _one(rng, design, n, sd, base, effect):
    if design == 'means':
        ma = rng.gauss(0.0, sd / math.sqrt(n))
        mb = rng.gauss(effect, sd / math.sqrt(n))
        se = math.sqrt(_sample_var(rng, sd, n) / n + _sample_var(rng, sd, n) / n)
        return mb - ma, se
    if design == 'paired':
        m = rng.gauss(effect, sd / math.sqrt(n))
        return m, math.sqrt(_sample_var(rng, sd, n) / n)
    pa, pb = base, base + effect
    xa = sum(1 for _ in range(n) if rng.random() < pa) / n
    xb = sum(1 for _ in range(n) if rng.random() < pb) / n
    se = math.sqrt(xa * (1 - xa) / n + xb * (1 - xb) / n)
    return xb - xa, se


def simulate(design, n, sd, scenarios, continue_if_lower_above, stop_if_upper_below, reps=2000, seed=20261114,
             alpha=0.05, base=None, threshold=0.8):
    if design not in ('means', 'proportions', 'paired'):
        raise ValueError('design must be means, proportions or paired')
    if not isinstance(n, int) or n < 2:
        raise ValueError('n must be an integer >= 2')
    if reps < 10:
        raise ValueError('reps must be >= 10')
    if not 0 < alpha < 1:
        raise ValueError('alpha must be in (0, 1)')
    if len(scenarios) < 2:
        raise ValueError('at least two scenarios (one per competing hypothesis)')
    names = [s[0] for s in scenarios]
    if len(set(names)) != len(names):
        raise ValueError('scenario names must be unique')
    if design in ('means', 'paired'):
        if sd is None or sd <= 0:
            raise ValueError('--sd > 0 is required for means and paired designs')
    else:
        if base is None or not 0 <= base <= 1:
            raise ValueError('--base in [0, 1] is required for proportions')
        for name, eff, _ in scenarios:
            if not 0 <= base + eff <= 1:
                raise ValueError('scenario %s: base + effect = %s is not a proportion' % (name, base + eff))
        if 2 * n * reps * len(scenarios) > MAX_DRAWS:
            raise ValueError('too many draws for the proportions design (n x reps x scenarios); lower --reps')
    for _, _, exp in scenarios:
        if exp is not None and exp not in DECISIONS:
            raise ValueError('expected decision must be one of %s' % ', '.join(DECISIONS))
    z = statistics.NormalDist().inv_cdf(1 - alpha / 2)
    rng = random.Random(seed)
    out_sc = []
    for name, eff, exp in scenarios:
        counts = dict.fromkeys(DECISIONS, 0)
        for _ in range(reps):
            est, se = _one(rng, design, n, sd, base, eff)
            counts[_decide(est - z * se, est + z * se, continue_if_lower_above, stop_if_upper_below)] += 1
        row = {'name': name, 'effect': eff, 'expected': exp}
        for d in DECISIONS:
            row['p_' + d] = counts[d] / reps
        row['p_expected'] = counts[exp] / reps if exp else None
        out_sc.append(row)
    expected = [r for r in out_sc if r['expected']]
    min_p = min((r['p_expected'] for r in expected), default=None)
    distinct = len({r['expected'] for r in expected}) >= 2
    return {
        'tool': 'frontier/sim.py', 'version': 1, 'design': design, 'n': n,
        'sd': sd if design != 'proportions' else None, 'base': base if design == 'proportions' else None,
        'alpha': alpha, 'reps': reps, 'seed': seed,
        'rule': {'continue_if_lower_above': continue_if_lower_above, 'stop_if_upper_below': stop_if_upper_below},
        'scenarios': out_sc,
        'distinguishes': bool(expected) and distinct and min_p is not None and min_p >= threshold
                         and len(expected) == len(out_sc),
        'min_p_expected': min_p, 'threshold': threshold,
    }


def rerun(sim):
    """Run simulate() again with the parameters stored in a sensitivity.simulation block (tools/check.py, R40)."""
    rule = sim['rule']
    sc = [(s['name'], s['effect'], s.get('expected')) for s in sim['scenarios']]
    return simulate(sim['design'], sim['n'], sim.get('sd'), sc, rule['continue_if_lower_above'],
                    rule['stop_if_upper_below'], reps=sim['reps'], seed=sim['seed'], alpha=sim['alpha'],
                    base=sim.get('base'), threshold=sim['threshold'])


def compare(stored, fresh, tol=1e-9):
    """Differences between a stored simulation block and a fresh rerun: list of 'field: stored != rerun'."""
    out = []

    def diff(where, a, b):
        if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str):
            if a != b:
                out.append('%s: %r != %r' % (where, a, b))
        elif not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or abs(a - b) > tol:
            out.append('%s: %r != %r' % (where, a, b))
    for k in ('distinguishes', 'min_p_expected'):
        diff(k, stored.get(k), fresh.get(k))
    st = stored.get('scenarios') or []
    fr = fresh.get('scenarios') or []
    if len(st) != len(fr):
        out.append('scenarios: %d stored, %d on rerun' % (len(st), len(fr)))
        return out
    for s, f in zip(st, fr):
        for k in ('name', 'expected') + tuple('p_' + d for d in DECISIONS) + ('p_expected',):
            diff('%s.%s' % (f.get('name'), k), s.get(k) if isinstance(s, dict) else None, f.get(k))
    return out


def needed_n(design, effect, sd=None, base=None, alpha=0.05, power=0.8, reps=2000, seed=20261114):
    """Size (per arm, or pairs) that detects `effect` with the given power: formula, then simulation check."""
    if design not in ('means', 'proportions', 'paired'):
        raise ValueError('design must be means, proportions or paired')
    if not isinstance(effect, (int, float)) or effect == 0:
        raise ValueError('--effect must be a non-zero number')
    if not 0 < alpha < 1 or not 0 < power < 1:
        raise ValueError('alpha and power must be in (0, 1)')
    if design == 'proportions':
        if base is None or not 0 <= base <= 1 or not 0 <= base + effect <= 1:
            raise ValueError('--base in [0, 1] with base + effect in [0, 1] is required for proportions')
    elif sd is None or sd <= 0:
        raise ValueError('--sd > 0 is required for means and paired designs')
    nd = statistics.NormalDist()
    za, zb = nd.inv_cdf(1 - alpha / 2), nd.inv_cdf(power)
    e = abs(effect)
    if design == 'means':
        n0 = 2 * (za + zb) ** 2 * sd * sd / (e * e)
    elif design == 'paired':
        n0 = (za + zb) ** 2 * sd * sd / (e * e)
    else:
        p1, p2 = base, base + effect
        pb = (p1 + p2) / 2
        n0 = (za * math.sqrt(2 * pb * (1 - pb)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2 / (e * e)
    n = max(2, int(math.ceil(n0)))
    scenarios = [('effect', effect, 'continue'), ('null', 0.0, 'indeterminate')]
    verified, p, note = True, None, 'formula, then a simulation check at a fixed seed'
    for _ in range(16):
        if design == 'proportions' and 2 * n * reps * len(scenarios) > MAX_DRAWS:
            verified, p, note = False, None, 'n too large for the simulation draw cap: formula only'
            break
        r = simulate(design, n, sd, scenarios, 0.0, -1e18, reps=reps, seed=seed, alpha=alpha, base=base)
        p = r['scenarios'][0]['p_continue']
        if p >= power - 0.02:
            break
        n = int(math.ceil(n * 1.1))
    else:
        verified, note = False, 'the simulated power stayed below the target after 16 increases of 10%'
    return {'tool': 'frontier/sim.py', 'version': 1, 'mode': 'needed_n', 'design': design, 'effect': effect,
            'sd': sd if design != 'proportions' else None, 'base': base if design == 'proportions' else None,
            'alpha': alpha, 'power_target': power, 'reps': reps, 'seed': seed, 'analytic_n': int(math.ceil(n0)),
            'needed_n': n, 'power_at_n': p, 'verified_by_simulation': verified, 'method': note}


def rerun_needed_n(block):
    return needed_n(block['design'], block['effect'], sd=block.get('sd'), base=block.get('base'), alpha=block['alpha'],
                    power=block['power_target'], reps=block['reps'], seed=block['seed'])


def compare_needed_n(stored, fresh, tol=1e-9):
    out = []
    for k in ('design', 'effect', 'sd', 'base', 'alpha', 'power_target', 'analytic_n', 'needed_n', 'verified_by_simulation'):
        if stored.get(k) != fresh.get(k):
            out.append('%s: %r != %r' % (k, stored.get(k), fresh.get(k)))
    a, b = stored.get('power_at_n'), fresh.get('power_at_n')
    if (a is None) != (b is None) or (a is not None and abs(a - b) > tol):
        out.append('power_at_n: %r != %r' % (a, b))
    return out


# ---------------------------------------------------------------- robust power (round 3, lot 4 / A5)
#
# robust(): the protocol-support simulation of a test whose outcome is a SERIES of n observations (paired differences, or
# the means design read on a series of differences). It answers what simulate() does not: what happens when the noise is
# not the noise assumed (sd perturbed over a range), when the observations are dependent in time (AR(1), parameter rho) or
# overlap (each observation sums h consecutive shocks, h = overlap), and it measures BOTH the false positives under the null
# and the power under the useful effect (and under 75% of it), with the analysis a careful researcher would run (a HAC
# standard error, Bartlett kernel, bandwidth max(h - 1, floor(4 (n / 100) ^ (2 / 9)))). The decision simulated is "continue":
# lower bound of the (1 - alpha) interval above continue_if_lower_above. effective_n_min = n / (h (1 + rho) / (1 - rho))
# at the worst rho (the usual variance inflation of an AR(1) mean, times the overlap): a description, not a correction.
# A simulation that supports the protocol is not an experiment: the card labels it so.

import functools
import operator


def _validate_robust(design, n, sd_values, rho_values, overlap, useful_effect, reps, alpha, effect_factors):
    if design not in ('means', 'paired'):
        raise ValueError('robust power is defined for the means and paired designs (a series of differences)')
    if not isinstance(n, int) or isinstance(n, bool) or n < 10:
        raise ValueError('n must be an integer >= 10')
    if not sd_values or any((not isinstance(s, (int, float))) or s <= 0 for s in sd_values):
        raise ValueError('every sd must be > 0')
    if not rho_values or any((not isinstance(r, (int, float))) or not -1 < r < 1 for r in rho_values):
        raise ValueError('every rho must lie strictly between -1 and 1')
    if not isinstance(overlap, int) or isinstance(overlap, bool) or overlap < 1:
        raise ValueError('overlap must be an integer >= 1')
    if not isinstance(useful_effect, (int, float)) or useful_effect == 0:
        raise ValueError('useful_effect must be a non-zero number')
    if reps < 10 or not 0 < alpha < 1 or not effect_factors or any(f <= 0 for f in effect_factors):
        raise ValueError('reps >= 10, 0 < alpha < 1 and positive effect factors are required')


def _series(rng, n, sd, rho, h, effect):
    burn, shocks, u = 25, [], rng.gauss(0.0, 1.0)
    root = math.sqrt(1.0 - rho * rho)
    for t in range(n + h - 1 + burn):
        u = rho * u + root * rng.gauss(0.0, 1.0)
        if t >= burn:
            shocks.append(u)
    if h > 1:
        scale, acc = 1.0 / math.sqrt(h), sum(shocks[:h])
        y = [acc * scale]
        for t in range(1, n):
            acc += shocks[t + h - 1] - shocks[t - 1]
            y.append(acc * scale)
    else:
        y = shocks
    return [effect + sd * v for v in y]


def _hac_se(x, bandwidth):
    n = len(x)
    m = sum(x) / n
    d = [v - m for v in x]
    tot = sum(v * v for v in d) / n
    for lag in range(1, bandwidth + 1):
        tot += 2.0 * (1.0 - lag / (bandwidth + 1.0)) * sum(map(operator.mul, d[lag:], d[:-lag])) / n
    return math.sqrt(max(tot, 1e-12) / n), m


def _robust_impl(key):
    p = json.loads(key)
    n, h, c, s = p['n'], p['overlap'], p['rule']['continue_if_lower_above'], p['rule']['stop_if_upper_below']
    z = statistics.NormalDist().inv_cdf(1 - p['alpha'] / 2)
    bw = max(h - 1, int(4 * (n / 100.0) ** (2.0 / 9.0)))
    rng = random.Random(p['seed'])
    scen = [('null', 0.0)] + [('useful x%g' % f, p['useful_effect'] * f) for f in p['effect_factors']]
    cells = []
    for sd in p['sd_values']:
        for rho in p['rho_values']:
            for label, eff in scen:
                cont = stop = 0
                decisions = dict.fromkeys(DECISIONS, 0)
                for _ in range(p['reps']):
                    se, m = _hac_se(_series(rng, n, sd, rho, h, eff), bw)
                    d = _decide(m - z * se, m + z * se, c, s)
                    decisions[d] += 1
                    cont += d in ('continue', 'revise')
                    stop += d in ('stop', 'revise')
                cells.append({'sd': sd, 'rho': rho, 'scenario': label, 'effect': eff,
                              'p_continue': cont / p['reps'], 'p_stop': stop / p['reps']})
                if p.get('decision_counts'):
                    cells[-1]['decision_counts'] = decisions
    nulls = [x['p_continue'] for x in cells if x['scenario'] == 'null']
    useful = [x['p_continue'] for x in cells if x['scenario'] != 'null']
    eff_n = min(n / (h * (1.0 + r) / (1.0 - r)) for r in p['rho_values'])
    out = dict(p)
    out.update({'tool': 'frontier/sim.py', 'version': 1, 'mode': 'robust', 'analysis': 'hac', 'hac_bandwidth': bw,
                'cells': cells, 'false_positive_max': max(nulls), 'power_min': min(useful), 'effective_n_min': eff_n,
                'note': 'protocol-support simulation (not an experiment): false positives under the null, power under the '
                        'useful effect and 75% of it, for every sd, dependence and overlap listed'})
    return json.dumps(out)


_robust_cached = functools.lru_cache(maxsize=64)(_robust_impl)


def robust(design, n, sd_values, rho_values, overlap, useful_effect, continue_if_lower_above, stop_if_upper_below,
           effect_factors=(1.0, 0.75), reps=120, seed=20261114, alpha=0.05, decision_counts=False):
    """Historical bound-crossing probabilities; opt in to exclusive decision counts.

    p_continue includes revise for compatibility. decision_counts['continue']
    counts only the rule's continue outcome; default output is unchanged.
    """
    sd_values, rho_values = sorted({float(x) for x in sd_values}), sorted({float(x) for x in rho_values})
    _validate_robust(design, n, sd_values, rho_values, overlap, useful_effect, reps, alpha, list(effect_factors))
    params = {'design': design, 'n': n, 'sd_values': sd_values, 'rho_values': rho_values, 'overlap': overlap,
                      'useful_effect': float(useful_effect), 'effect_factors': [float(f) for f in effect_factors],
                      'alpha': alpha, 'reps': reps, 'seed': seed,
                      'rule': {'continue_if_lower_above': continue_if_lower_above, 'stop_if_upper_below': stop_if_upper_below}}
    if decision_counts:
        params['decision_counts'] = True
    return json.loads(_robust_cached(json.dumps(params, sort_keys=True)))


def rerun_robust(block):
    r = block['rule']
    return robust(block['design'], block['n'], block['sd_values'], block['rho_values'], block['overlap'], block['useful_effect'],
                  r['continue_if_lower_above'], r['stop_if_upper_below'], tuple(block['effect_factors']), block['reps'],
                  block['seed'], block['alpha'])


def compare_robust(stored, fresh, tol=1e-9):
    out = []
    for k in ('false_positive_max', 'power_min', 'effective_n_min'):
        a, b = stored.get(k), fresh.get(k)
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or abs(a - b) > tol:
            out.append('%s: %r != %r' % (k, a, b))
    sc, fc = stored.get('cells') or [], fresh.get('cells') or []
    if len(sc) != len(fc):
        out.append('cells: %d stored, %d on rerun' % (len(sc), len(fc)))
        return out
    for i, (a, b) in enumerate(zip(sc, fc)):
        for k in ('sd', 'rho', 'scenario', 'effect', 'p_continue', 'p_stop'):
            x, y = a.get(k) if isinstance(a, dict) else None, b.get(k)
            same = (x == y) if isinstance(x, str) or isinstance(y, str) else (
                isinstance(x, (int, float)) and isinstance(y, (int, float)) and abs(x - y) <= tol)
            if not same:
                out.append('cells[%d].%s: %r != %r' % (i, k, x, y))
    return out


def main_robust(argv):
    ap = argparse.ArgumentParser(prog='sim.py robust', description='Robust power of a test of tests.json (see the module docstring)')
    ap.add_argument('--design', required=True, choices=['means', 'paired', 'proportions'])
    ap.add_argument('--tests', required=True, help='tests.json whose test holds sensitivity.power.parameters (n, sd) and the rule thresholds')
    ap.add_argument('--test', required=True)
    ap.add_argument('--useful-effect', type=float, required=True)
    ap.add_argument('--rho', default='0', help='comma list of AR(1) parameters')
    ap.add_argument('--overlap', type=int, default=1)
    ap.add_argument('--reps', type=int, default=120)
    ap.add_argument('--seed', type=int, default=20261114)
    ap.add_argument('--alpha', type=float, default=0.05)
    a = ap.parse_args(argv)
    try:
        data = json.loads(Path(a.tests).read_text(encoding='utf-8'))
        t = next((x for x in data.get('tests', []) if isinstance(x, dict) and x.get('id') == a.test), None)
        if t is None:
            raise ValueError('test %s not found in %s' % (a.test, a.tests))
        pw = (t.get('sensitivity') or {}).get('power')
        params = {p.get('name'): p for p in (pw or {}).get('parameters') or [] if isinstance(p, dict)}
        if 'n' not in params or 'sd' not in params:
            raise ValueError('sensitivity.power.parameters must hold n and sd (write them first)')
        n = params['n'].get('central', params['n'].get('value'))
        sds = [params['sd'][k] for k in ('low', 'central', 'high') if k in params['sd']] or [params['sd'].get('value')]
        th = (t.get('decision_rule') or {}).get('thresholds')
        if not isinstance(th, dict):
            raise ValueError('the test needs decision_rule.thresholds (run the ordinary simulation first)')
        out = robust(a.design, int(n), sds, [float(x) for x in a.rho.split(',')], a.overlap, a.useful_effect,
                     th['continue_if_lower_above'], th['stop_if_upper_below'], reps=a.reps, seed=a.seed, alpha=a.alpha)
        pw['robust'] = out
        Path(a.tests).write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    except (ValueError, OSError, KeyError, TypeError) as e:
        print('sim.py: %s' % e, file=sys.stderr)
        return 2
    print(json.dumps({k: out[k] for k in ('false_positive_max', 'power_min', 'effective_n_min')}))
    return 0


NEEDED_PARAMS = {'means': ('n', 'sd'), 'paired': ('n', 'sd'), 'proportions': ('n', 'base')}


def context_block(intake, cli, needed):
    """Which of the parameters `needed` come from the confirmed context numbers of intake, which from the command line.
    cli = {param: value or None}. Returns (values, block); a value the command line gives wins, and the gap is written."""
    ci = common.context_inputs(intake) if isinstance(intake, dict) else {}
    block = {'used': False, 'inputs': {}, 'not_from_context': [], 'missing': [], 'differs': {}, 'note': ''}
    values = {}
    for p in needed:
        c, cv = ci.get(p), cli.get(p)
        if c is None:
            block['missing'].append(p)
        if cv is not None:
            values[p] = cv
            block['not_from_context'].append(p)
            if c is not None and cv != c['value']:
                block['differs'][p] = {'context': c['value'], 'command_line': cv}
        elif c is not None:
            values[p] = c['value']
            block['inputs'][p] = {'name': c['name'], 'value': c['value'], 'cited': c.get('cited'), 'source': c.get('source')}
        else:
            block['not_from_context'].append(p)
    block['used'] = bool(block['inputs'])
    if not isinstance(intake, dict):
        block['note'] = ("no project context given: %s are values chosen by hand, not the project's measured numbers"
                         % ', '.join(needed))
    elif block['used']:
        block['note'] = 'from the project context: %s' % ', '.join(
            '%s = %s (%s)' % (p, v['value'], v['name']) for p, v in block['inputs'].items())
        if block['not_from_context']:
            block['note'] += '; by hand: %s' % ', '.join(block['not_from_context'])
    else:
        block['note'] = ("the project context holds no confirmed key number for %s: values chosen by hand, power not tied to "
                         "the project's numbers" % ', '.join(needed))
    return values, block


def _read_context(path):
    p = Path(path)
    p = p / 'intake.json' if p.is_dir() else p
    return common.read_json(p)


def _pairs(values, cast, what):
    out = []
    for v in values or []:
        if '=' not in v:
            raise ValueError('%s must be NAME=VALUE: %r' % (what, v))
        k, x = v.split('=', 1)
        out.append((k.strip(), cast(x.strip())))
    return out


def rule_thresholds(path, test_id):
    """decision_rule.thresholds of a test of tests.json, or None."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    for t in data.get('tests', []) if isinstance(data, dict) else []:
        if isinstance(t, dict) and t.get('id') == test_id:
            th = (t.get('decision_rule') or {}).get('thresholds')
            return th if isinstance(th, dict) else None
    return None


def write_into(path, test_id, sim):
    """Copy the simulation into sensitivity.simulation of the test, and its two thresholds into
    decision_rule.thresholds (the structured core of the rule the simulation tests, R41)."""
    path = Path(path)
    data = json.loads(path.read_text(encoding='utf-8'))
    for t in data.get('tests', []):
        if isinstance(t, dict) and t.get('id') == test_id:
            sens = t.setdefault('sensitivity', {})
            sens['simulation'] = sim
            sens.pop('simulation_not_applicable', None)
            rule = t.setdefault('decision_rule', {})
            if isinstance(rule, dict):
                rule['thresholds'] = dict(sim['rule'])
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            return True
    return False


def write_entry(path, entry_id, block):
    """Store the needed-n block in needed_test_size of one entry of evidence_table.json."""
    path = Path(path)
    data = json.loads(path.read_text(encoding='utf-8'))
    for e in data.get('entries', []) if isinstance(data, dict) else []:
        if isinstance(e, dict) and e.get('id') == entry_id:
            e['needed_test_size'] = block
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            return True
    return False


def main_needed(a):
    try:
        if a.effect is None:
            raise ValueError('--needed-n needs --effect')
        if a.write_into and not a.entry:
            raise ValueError('--needed-n --write-into needs --entry')
        intake = _read_context(a.context) if a.context else None
        want = ('sd',) if a.design in ('means', 'paired') else ('base',)
        values, cblock = context_block(intake, {'sd': a.sd, 'base': a.base}, want)
        for p in want:
            if p not in values:
                raise ValueError('--%s is required (the project context has no confirmed number for it either)' % p)
        out = needed_n(a.design, a.effect, sd=values.get('sd'), base=values.get('base'), alpha=a.alpha, power=a.power,
                       reps=a.reps, seed=a.seed)
        out['context'] = cblock
    except (ValueError, OSError) as e:
        print('sim.py: %s' % e, file=sys.stderr)
        return 2
    if a.write_into and not write_entry(a.write_into, a.entry, out):
        print('sim.py: entry %s not found in %s' % (a.entry, a.write_into), file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] == 'robust':
        return main_robust(argv[1:])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--design', required=True, choices=['means', 'proportions', 'paired'])
    ap.add_argument('--n', type=int)
    ap.add_argument('--context', help='working directory (or intake.json) whose confirmed key numbers fill n, sd, base')
    ap.add_argument('--needed-n', action='store_true', help='compute the size needed for --effect instead of simulating')
    ap.add_argument('--effect', type=float)
    ap.add_argument('--power', type=float, default=0.8)
    ap.add_argument('--entry', help='with --needed-n --write-into: the entry id of evidence_table.json')
    ap.add_argument('--sd', type=float)
    ap.add_argument('--base', type=float)
    ap.add_argument('--scenario', action='append')
    ap.add_argument('--expect', action='append')
    ap.add_argument('--continue-if-lower-above', type=float, default=None)
    ap.add_argument('--stop-if-upper-below', type=float, default=None)
    ap.add_argument('--alpha', type=float, default=0.05)
    ap.add_argument('--reps', type=int, default=2000)
    ap.add_argument('--seed', type=int, default=20261114)
    ap.add_argument('--threshold', type=float, default=0.8)
    ap.add_argument('--write-into')
    ap.add_argument('--test')
    a = ap.parse_args(argv)
    if a.needed_n:
        return main_needed(a)
    try:
        intake = _read_context(a.context) if a.context else None
        want = ('n', 'sd') if a.design in ('means', 'paired') else ('n', 'base')
        values, cblock = context_block(intake, {'n': a.n, 'sd': a.sd, 'base': a.base}, want)
        for p in want:
            if p not in values:
                raise ValueError('--%s is required (the project context has no confirmed number for it either)' % p)
        n = values['n']
        if int(n) != n:
            raise ValueError('n must be an integer (found %r)' % n)
        a.n, a.sd, a.base = int(n), values.get('sd', a.sd), values.get('base', a.base)
        sc = _pairs(a.scenario, float, '--scenario')
        exp = dict(_pairs(a.expect, str, '--expect'))
        unknown = set(exp) - {n for n, _ in sc}
        if unknown:
            raise ValueError('--expect names unknown scenarios: %s' % ', '.join(sorted(unknown)))
        if a.write_into and not a.test:
            raise ValueError('--write-into needs --test')
        c, s = a.continue_if_lower_above, a.stop_if_upper_below
        th = rule_thresholds(a.write_into, a.test) if a.write_into else None
        if th:
            # the thresholds of the decision rule fixed in tests.json are the ones simulated (R41)
            if (c is not None and c != th.get('continue_if_lower_above')) or \
                    (s is not None and s != th.get('stop_if_upper_below')):
                raise ValueError('the thresholds given differ from decision_rule.thresholds of %s in %s; change the '
                                 'rule itself, or give the same values' % (a.test, a.write_into))
            c, s = th.get('continue_if_lower_above'), th.get('stop_if_upper_below')
        c = 0.0 if c is None else c
        s = 0.0 if s is None else s
        out = simulate(a.design, a.n, a.sd, [(n, e, exp.get(n)) for n, e in sc], c, s, reps=a.reps, seed=a.seed,
                       alpha=a.alpha, base=a.base, threshold=a.threshold)
        out['context'] = cblock
    except (ValueError, OSError) as e:
        print('sim.py: %s' % e, file=sys.stderr)
        return 2
    if a.write_into and not write_into(a.write_into, a.test, out):
        print('sim.py: test %s not found in %s' % (a.test, a.write_into), file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
