#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Checks of Frontier round 3 (round-3 plan, adjustments A1-A9 prevail). Called by tools/check.py; offline, no model.

Two groups:
  EVERY directory   [ARITH-STRATA] [ARITH-PERIOD] [ARITH-N]   arithmetic of the tests (3.1): a number of strata, of periods or
                    of replications that the data declared in the same text cannot hold.
  R3 directories    (intake.json frontier_version 3, or the frontier-version.json that tools/new_run.py writes)
    [TOMORROW]      recommendation.json tomorrow = {test (the first of ranking.order), first_action}: the card derives the
                    other lines of "Tomorrow" from that test (2.2).
    [LOG-AFTER]     an "after" written by assumption, or without an executed result or an observation (2.3).
    [REB-AFTER-ASSUMED] is raised in tools/check.py (rebound_after.json whose outcome is an assumption).
    [FIX-PROOF] [FIX-UNCONFIRMED]  a "fixed" critique item needs a mechanically checked proof and the second critique (A1).
    [RECO-OPEN]     advisory mark: "dig" while a blocking critique item is open.
    [DATA-SEEN]     data_seen_before missing, or overlapping the confirmation data (3.3).
    [SCOPE]         verdict_scope missing, or a rule that concludes beyond what the test tested (3.4).
    [POWER-MISSING] [POWER-FIELD] [POWER-TARGET] [POWER-RANGE] [POWER-SOURCE] [POWER-LINK] [POWER-RERUN]   sensitivity.power (4.1, A5).
    [DECISIVE] [DECISIVE-FRAGMENT] [DECISIVE-OVERCLAIM]   decisive_claims.json and recommendation.justification (5.1, A6).
    [COVER-STALE] [RECALL-CLAIM]  prior_art.coverage is computed from the VP journal; no recall is ever claimed (5.2, A4).
    [DRAFT-SUPPORT] [DRAFT-DECISIVE]  a verified claim of the free draft carries its explicit support; a draft claim that decides
                    is verified or marked (Terra, 6.1).
    [PROV-MISMATCH] a saved gateway answer that the gateway journal contradicts (1.2, A3); unverified provenance is a warning.
    [BUDGET]        a second critique without its "critique2" step.
Import: run(work, data, P, W, ck) with ck = the tools/check.py module; arith(tests_json, P); card_truncation(text).
"""
import json
import math
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ written in the skill directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import guards  # noqa: E402
import hybrid  # noqa: E402

TRUNC = re.compile(r'…|\.\.\.|\(\+\d+ (?:more|earlier)')
NUM = re.compile(r'-?\d+(?:\.\d+)?')
STOPW = frozenset('that this with from into than then when which what where about over under between within without each '
                  'such more most some have been were does should would could their there these those only also very just'.split())
E_ACUTE = chr(0xe9)       # the sources of Frontier carry no accented letter (tests/test_docs.py): built from code points
RANGE = re.compile(r'((?:19|20)\d\d)\s*(?:-|' + chr(0x2013) + '|' + chr(0x2014) + r'|to|' + chr(0xe0) + r'|au|and|et)\s*((?:19|20)\d\d)')
ISO = re.compile(r'((?:19|20)\d\d)-(\d\d)-(\d\d)')
YEAR = re.compile(r'(?<![\d-])((?:19|20)\d\d)(?![\d-])')
OVERCLAIM = re.compile(r"\bidea\s+(?:is|are)\s+(?:false|wrong|refuted|dead|disproved|invalid)\b|\brefute[sd]?\s+the\s+(?:whole\s+)?idea\b"
                       r"|\bdrop\s+the\s+(?:whole\s+)?idea\b|\bid[" + E_ACUTE + r"e]e\s+est\s+(?:fausse|r[" + E_ACUTE + r"e]fut["
                       + E_ACUTE + r"e]e|morte)\b", re.I)
RECALL = re.compile(r'\brecall\b|\brappel\b', re.I)
LEVELS = (('tercile', 3), ('tertile', 3), ('quartile', 4), ('quintile', 5), ('decile', 10))        # the text is folded (accent-free) before this is looked up


def text(x):
    return x.strip() if isinstance(x, str) else ''


def norm(s):
    return re.sub(r'\s+', ' ', text(s).lower())


def words(s):
    return {w for w in common.words(s) if len(w) >= 4 and w not in STOPW}


def strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)


def card_truncation(card_text):
    """Truncation marks of a card: an ellipsis, three dots, or a "(+N more" pointer (all distinct occurrences)."""
    return sorted(set(TRUNC.findall(card_text or '')))


# ---------------------------------------------------------------- arithmetic (every directory)


def _months_between(s):
    m = ISO.findall(s)
    if len(m) >= 2:
        (y1, m1, _), (y2, m2, _) = m[0], m[1]
        return (int(y2) - int(y1)) * 12 + (int(m2) - int(m1)) + 1
    r = RANGE.search(s)
    if r:
        return (int(r.group(2)) - int(r.group(1)) + 1) * 12
    return None


def arith_strings(s):
    """[(code, message)] for one text."""
    out = []
    low = common.fold(s)
    for m in re.finditer(r'(\d+)\s+(?:strates?|strata|stratum)\b', low):
        n = int(m.group(1))
        months = _months_between(s)
        if months is None or not re.search(r'\bmois\b|\bmonths?\b', low):
            continue
        cap = months
        for word, k in LEVELS:
            if word in low:
                cap *= k
                break
        if n > cap:
            out.append(('[ARITH-STRATA]', '%d strata cannot be built from %d month(s)%s of the dates given in the same text '
                        '(at most %d)' % (n, months, ' x levels' if cap != months else '', cap)))
    r = RANGE.search(s)
    if r:
        years = int(r.group(2)) - int(r.group(1)) + 1
        for m in re.finditer(r'(\d+)\s*(mois|months?|ans|years?|trimestres?|quarters?)\b', low):
            gap = min(abs(m.start() - r.end()), abs(r.start() - m.end()))
            if gap > 20:
                continue
            unit = m.group(2)
            cap = years * (12 if unit.startswith(('mois', 'month')) else 4 if unit.startswith(('trim', 'quarter')) else 1)
            if int(m.group(1)) > cap:
                out.append(('[ARITH-PERIOD]', '%s %s do not fit in %s-%s (%d at most)' % (m.group(1), unit, r.group(1), r.group(2), cap)))
    return out


def arith(tj, P, W=None, strict_n=True):
    """strata and periods always refuse; the n of the simulation against the replications refuses in R3 directories and is a
    warning in older ones (an existing fixture simulates n = 20 beside "200 records": its contract is kept)."""
    W = [] if W is None else W
    for t in (tj.get('tests') if isinstance(tj, dict) else None) or []:
        if not isinstance(t, dict):
            continue
        tid = t.get('id', '?')
        for s in strings({k: v for k, v in t.items() if k not in ('predictions',)}):
            for code, msg in arith_strings(s):
                P.append('%s tests.json: %s: %s' % (code, tid, msg))
        sens = t.get('sensitivity') if isinstance(t.get('sensitivity'), dict) else {}
        sim = sens.get('simulation')
        rep = sens.get('replications')
        if isinstance(sim, dict) and isinstance(sim.get('n'), int):
            if isinstance(rep, int) and not isinstance(rep, bool):
                nums = [rep]
            else:
                nums = [int(x.replace(',', '').replace(' ', '')) for x in re.findall(r'\d[\d, ]*\d|\d', text(rep)) if x.strip()]
                nums = [n for n in nums if n > 0]
            if nums and sim['n'] not in nums:
                msg = ('[ARITH-N] tests.json: %s: the simulation uses n = %d but sensitivity.replications says %r'
                       % (tid, sim['n'], rep))
                (P if strict_n else W).append(msg)


# ---------------------------------------------------------------- helpers on VP runs


def vp_claim(work, intake, run, claim):
    """({status, fragments}) of a claim of a VP run, or None."""
    runs = ((intake or {}).get('vp') or {}).get('runs') or {}
    path = runs.get(run) if isinstance(runs, dict) else None
    if not isinstance(path, str):
        return None
    d = Path(path)
    d = d if d.is_absolute() else Path(work) / d
    try:
        v = json.loads((d / 'verdicts.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    for c in v.get('claims') or []:
        if isinstance(c, dict) and c.get('id') == claim:
            return {'status': c.get('status'), 'fragments': [f for f in c.get('fragments') or [] if isinstance(f, str)]}
    return None


def fragment_ok(fragment, fragments):
    f = norm(fragment)
    return len(f) >= 8 and any(f in norm(x) or norm(x) in f for x in fragments)


# ---------------------------------------------------------------- R3 checks


def check_tomorrow(reco, tj, P):
    tm = reco.get('tomorrow') if isinstance(reco, dict) else None
    order = ((tj or {}).get('ranking') or {}).get('order') or []
    if not isinstance(tm, dict):
        P.append('[TOMORROW] recommendation.json: tomorrow = {test, first_action} is required (the first gesture of tomorrow)')
        return
    if not order or tm.get('test') != order[0]:
        P.append('[TOMORROW] recommendation.json: tomorrow.test is %r but the first test of ranking.order is %r' % (tm.get('test'), order[:1]))
    if common.is_placeholder(tm.get('first_action'), 30):
        P.append('[TOMORROW] recommendation.json: tomorrow.first_action must say the first gesture (30 characters or more)')


def check_log_after(work, data, ck, P):
    entries, _ = ck.read_log(work)
    res = data.get('result.json')
    executed = res.get('test') if isinstance(res, dict) and res.get('mode') == 'executed' else None
    for e in entries or []:
        if e.get('phase') != 'after':
            continue
        if e.get('by') == 'assumption':
            P.append('[LOG-AFTER] decision_log.jsonl: an "after" for %s was written by assumption: it is a scenario, not a '
                     'result (put it in tests.json ranking.scenarios)' % e.get('test'))
        elif e.get('test') != executed and len(text(e.get('observed'))) < 20:
            P.append('[LOG-AFTER] decision_log.jsonl: the "after" for %s has neither an executed result nor an observation '
                     '(tools/log.py after --observed ...)' % e.get('test'))


def resolve(tj, where):
    """Value at a path "tests.T1.traps.positive_control.description" of tests.json, or None."""
    parts = text(where).split('.')
    if len(parts) < 3 or parts[0] != 'tests':
        return None
    cur = next((t for t in (tj or {}).get('tests') or [] if isinstance(t, dict) and t.get('id') == parts[1]), None)
    for k in parts[2:]:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        elif isinstance(cur, list) and k.isdigit() and int(k) < len(cur):
            cur = cur[int(k)]
        else:
            return None
    return cur


def proof_problem(work, data, item, ck):
    pr = (item.get('response') or {}).get('proof')
    if not isinstance(pr, dict):
        return 'no proof: a "fixed" correction needs a file, a calculation, a passage or a changed protocol that answers the objection'
    kind, where, ev = pr.get('kind'), pr.get('where'), text(pr.get('evidence'))
    if len(words(pr.get('addresses', '')) & words(item.get('text', ''))) < 2:
        return 'the proof does not say which part of the objection it answers (addresses shares fewer than 2 content words with it)'
    if kind == 'tests_diff':
        val = resolve(data.get('tests.json'), where)
        if val is None:
            return 'where = %r is not a field of tests.json' % where
        if len(ev) < 15 or norm(ev) not in norm(val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)):
            return 'the quoted evidence is not in %s' % where
        return None
    if kind == 'calculation':
        val = resolve(data.get('tests.json'), where)
        if not isinstance(val, dict) or val.get('tool') != 'frontier/sim.py':
            return 'where = %r is not a block written by tools/sim.py' % where
        nums = NUM.findall(ev)
        blob = json.dumps(val)
        if not nums or any(n not in blob for n in nums):
            return 'the figures quoted (%s) are not in the stored simulation block' % ', '.join(nums) if nums else 'no figure quoted'
        return None
    if kind == 'file':
        rel = Path(text(where))
        if rel.is_absolute() or '..' in rel.parts or not (Path(work) / rel).is_file():
            return 'file %r is not a file of this directory' % where
        if common.sha256_file(Path(work) / rel) != ev:
            return 'the SHA-256 given is not the one of %s' % where
        return None
    if kind == 'passage':
        run, _, claim = text(where).partition(':')
        c = vp_claim(work, data.get('intake.json'), run, claim)
        if c is None or c['status'] in (None, 'ABSENT', 'INVALID'):
            return 'VP claim %r has no valid verdict' % where
        return None if fragment_ok(ev, c['fragments']) else 'the quoted passage is not a fragment of the VP verdict'
    return 'proof kind %r is not one of tests_diff, calculation, file, passage' % kind


def check_fixes(work, data, ck, P, W):
    cr = data.get('critique.json')
    if not isinstance(cr, dict):
        return
    items = [it for it in cr.get('items') or [] if isinstance(it, dict)]
    sc = cr.get('second_critique') if isinstance(cr.get('second_critique'), dict) else None
    corpus, confirmed = None, {}
    if sc is not None:
        cfg = common.config()
        if (cr.get('same_family') is False and common.family(sc.get('critic_family'), cfg) == common.family(cr.get('author_family'), cfg)):
            P.append('[FIX-UNCONFIRMED] critique.json second_critique: the second critic is of the author\'s own family while the '
                     'first critique had an independent critic: a model does not confirm its own corrections')
        rel = text(sc.get('raw_output'))
        p = Path(work) / rel if rel and not Path(rel).is_absolute() and '..' not in Path(rel).parts else None
        if p is None or not p.is_file():
            P.append('[FIX-UNCONFIRMED] critique.json second_critique: raw_output %r is not a file of this directory' % rel)
        elif common.sha256_file(p) != sc.get('raw_sha256'):
            P.append('[FIX-UNCONFIRMED] critique.json second_critique: raw_sha256 is not the one of %s (changed after receipt)' % rel)
        else:
            corpus = ck.raw_corpus(p.read_bytes())
        for v in sc.get('verdicts') or []:
            if isinstance(v, dict) and isinstance(v.get('item'), int):
                if corpus is not None and norm(v.get('why')) not in corpus:
                    P.append('[FIX-UNCONFIRMED] critique.json second_critique: the reason for item %s is not in the raw answer' % v['item'])
                    continue
                if corpus is not None:
                    confirmed[v['item']] = v.get('objection_lifted')
    for i, it in enumerate(items):
        action = (it.get('response') or {}).get('action')
        if action != 'fixed':
            continue
        why = proof_problem(work, data, it, ck)
        if why:
            P.append('[FIX-PROOF] critique.json items[%d]: %s' % (i, why))
        if confirmed.get(i) != 'yes':
            P.append('[FIX-UNCONFIRMED] critique.json items[%d] is "fixed" but the second critique %s: it stays "open" until the '
                     'critic confirms that the objection is lifted' % (i, 'did not confirm it (%s)' % confirmed[i] if i in confirmed
                                                                         else 'has no verdict on it'))
    reco = data.get('recommendation.json')
    if isinstance(reco, dict) and reco.get('verdict') == 'dig' and any(
            it.get('severity') == 'blocking' and (it.get('response') or {}).get('action') == 'open' for it in items):
        W.append('mark: [RECO-OPEN] recommendation.json: "dig" while an objection with critic severity blocking remains open')
    steps = []
    try:
        steps = json.loads((Path(work) / 'run.json').read_text(encoding='utf-8')).get('steps') or []
    except (OSError, ValueError):
        pass
    if sc is not None and not any(isinstance(s, dict) and s.get('step') == 'critique2' for s in steps):
        P.append('[BUDGET] run.json: critique.json has a second_critique but no "critique2" step is recorded')


def years_of(s):
    s = text(s)
    out = [(int(a), int(b)) for a, b in RANGE.findall(s)]
    rest = RANGE.sub(' ', s)
    out += [(int(y), int(y)) for y in YEAR.findall(rest)]
    return [(min(a, b), max(a, b)) for a, b in out]


def check_tests_r3(work, data, ck, P, W):
    tj = data.get('tests.json')
    intake = data.get('intake.json')
    for t in (tj.get('tests') if isinstance(tj, dict) else None) or []:
        if not isinstance(t, dict):
            continue
        tid = t.get('id', '?')
        ds = ((t.get('traps') or {}).get('data_split')) or {}
        seen = ds.get('data_seen_before')
        if common.is_placeholder(seen, 20):
            P.append('[DATA-SEEN] tests.json: %s: traps.data_split.data_seen_before is required: what period or sample was '
                     'already consulted, or "nothing consulted" and why' % tid)
        else:
            gone = years_of(seen) + years_of(ds.get('design_data'))
            for a, b in years_of(ds.get('confirmation_data')):
                if any(a <= y2 and y1 <= b for y1, y2 in gone):
                    P.append('[DATA-SEEN] tests.json: %s: the confirmation data (%s-%s) overlap data already seen or used for '
                             'the design: a consulted period cannot confirm' % (tid, a, b))
                    break
        sc = t.get('verdict_scope')
        dn = sc.get('does_not_conclude_about') if isinstance(sc, dict) else None
        if (not isinstance(sc, dict) or common.is_placeholder(sc.get('concludes_about'), 20) or not isinstance(dn, list) or not dn
                or any(common.is_placeholder(x, 10) for x in dn)):
            P.append('[SCOPE] tests.json: %s: verdict_scope = {concludes_about, does_not_conclude_about: [...]} is required: a '
                     'test concludes only on what it tested' % tid)
        for b in ('continue_if', 'revise_if', 'stop_if', 'indeterminate_if'):
            m = OVERCLAIM.search(text((t.get('decision_rule') or {}).get(b)))
            if m:
                P.append('[SCOPE] tests.json: %s: decision_rule.%s concludes on the whole idea (%r): a test concludes only on '
                         'what it tested' % (tid, b, m.group(0)))
        check_power(work, intake, data, t, tid, ck, P, W)


def _param_value(p):
    return p.get('central') if p.get('status') == 'assumed' else p.get('value')


def check_power(work, intake, data, t, tid, ck, P, W):
    sens = t.get('sensitivity') if isinstance(t.get('sensitivity'), dict) else {}
    pw = sens.get('power')
    if not isinstance(pw, dict):
        P.append('[POWER-MISSING] tests.json: %s: sensitivity.power is required (target metric, costs, data, prior trials, '
                 'parameters measured or assumed, dependence model)' % tid)
        return
    if pw.get('role') != 'protocol_support':
        P.append('[POWER-FIELD] tests.json: %s: sensitivity.power.role must be "protocol_support" (a simulation that supports '
                 'the protocol is not an experiment)' % tid)
    if common.is_placeholder(pw.get('target_metric'), 10):
        P.append('[POWER-TARGET] tests.json: %s: sensitivity.power.target_metric names the metric the decision is about' % tid)
    if not isinstance(pw.get('metric_is_target'), bool):
        P.append('[POWER-TARGET] tests.json: %s: sensitivity.power.metric_is_target must be true or false' % tid)
    elif pw['metric_is_target'] is False and common.is_placeholder(pw.get('proxy_gap'), 30):
        P.append('[POWER-TARGET] tests.json: %s: the metric simulated is not the target metric: write proxy_gap (what the proxy '
                 'leaves out)' % tid)
    for f in ('costs', 'data_available', 'prior_trials'):
        if common.is_placeholder(pw.get(f), 15):
            P.append('[POWER-FIELD] tests.json: %s: sensitivity.power.%s is empty or a placeholder' % (tid, f))
    model = pw.get('model') if isinstance(pw.get('model'), dict) else {}
    for f, n in (('dependence', 15), ('overlap', 15), ('justification', 40)):
        if common.is_placeholder(model.get(f), n):
            P.append('[POWER-FIELD] tests.json: %s: sensitivity.power.model.%s must justify the simulation model (%d characters or '
                     'more)' % (tid, f, n))
    params = [p for p in pw.get('parameters') or [] if isinstance(p, dict)]
    if not params:
        P.append('[POWER-FIELD] tests.json: %s: sensitivity.power.parameters is empty' % tid)
    ctx = {k.get('name'): k for k in ((intake or {}).get('context') or {}).get('key_numbers') or [] if isinstance(k, dict)}
    byname = {}
    for p in params:
        byname[p.get('name')] = p
        st = p.get('status')
        if st == 'assumed':
            lo, ce, hi = (p.get(k) for k in ('low', 'central', 'high'))
            if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (lo, ce, hi)) or not lo <= ce <= hi or lo >= hi:
                P.append('[POWER-RANGE] tests.json: %s: parameter %s is assumed: give a range low <= central <= high (low < high), '
                         'not a single figure' % (tid, p.get('name')))
        elif st == 'measured':
            src = p.get('source') if isinstance(p.get('source'), dict) else {}
            kind = src.get('kind')
            if kind in ('context', 'user'):
                k = ctx.get(src.get('name'))
                usable = k is not None and (k.get('confirmed') is True or (k.get('source') == 'user' and k.get('confirmed') is not False))
                if not usable:
                    P.append('[POWER-SOURCE] tests.json: %s: parameter %s is "measured" from context %r, which is not a confirmed key '
                             'number of intake.json' % (tid, p.get('name'), src.get('name')))
                elif k.get('value') != p.get('value'):
                    P.append('[POWER-SOURCE] tests.json: %s: parameter %s = %r but the key number %s is %r' % (
                        tid, p.get('name'), p.get('value'), src.get('name'), k.get('value')))
            elif kind == 'reference':
                ref = src.get('ref') if isinstance(src.get('ref'), dict) else None
                vp = ck.VPRuns(work, intake) if ck.get(intake, 'vp', 'mode') == 'vp' else None
                if ref is None or vp is None:
                    P.append('[POWER-SOURCE] tests.json: %s: parameter %s is "measured" from a reference, which needs VP and '
                             '{id, run, claim}' % (tid, p.get('name')))
                else:
                    _, code, msg = ck.ref_check(vp, ref)
                    if code:
                        P.append('[POWER-SOURCE] tests.json: %s: parameter %s: %s %s' % (tid, p.get('name'), code, msg))
            else:
                P.append('[POWER-SOURCE] tests.json: %s: parameter %s is "measured" without a source (context, user or reference): '
                         'say "assumed" and give a range' % (tid, p.get('name')))
            if not isinstance(p.get('value'), (int, float)) or isinstance(p.get('value'), bool):
                P.append('[POWER-SOURCE] tests.json: %s: parameter %s has no numeric value' % (tid, p.get('name')))
        else:
            P.append('[POWER-FIELD] tests.json: %s: parameter %s must be "measured" (with source) or "assumed" (with a range)'
                     % (tid, p.get('name')))
    sim = sens.get('simulation')
    if not isinstance(sim, dict):
        if common.is_placeholder(pw.get('not_applicable_why'), 30):
            P.append('[POWER-FIELD] tests.json: %s: no simulation: sensitivity.power.not_applicable_why says why' % tid)
        return
    n = byname.get('n')
    if n is None or _param_value(n) != sim.get('n'):
        P.append('[POWER-LINK] tests.json: %s: the simulation uses n = %r but the power parameter n is %r (central or measured)'
                 % (tid, sim.get('n'), _param_value(n) if n else None))
    rb = pw.get('robust')
    if sim.get('design') == 'proportions':
        if common.is_placeholder(pw.get('robust_not_applicable'), 30):
            P.append('[POWER-RERUN] tests.json: %s: the proportions design has no robust simulation: write robust_not_applicable' % tid)
        return
    if not isinstance(rb, dict):
        P.append('[POWER-RERUN] tests.json: %s: sensitivity.power.robust is missing: run python3 -I <SKILL_DIR>/tools/sim.py robust '
                 '--tests tests.json --test %s ...' % (tid, tid))
        return
    sd = byname.get('sd')
    want = sorted({float(sd[k]) for k in ('low', 'central', 'high') if k in sd} or ({float(sd['value'])} if sd and 'value' in sd else set())) if sd else []
    if rb.get('n') != sim.get('n') or rb.get('sd_values') != want:
        P.append('[POWER-LINK] tests.json: %s: robust simulation was made for n = %r and sd %r, not for the power parameters (n %r, sd %r)'
                 % (tid, rb.get('n'), rb.get('sd_values'), sim.get('n'), want))
    try:
        import sim as simmod
        diffs = simmod.compare_robust(rb, simmod.rerun_robust(rb))
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        P.append('[POWER-RERUN] tests.json: %s: the robust simulation cannot be rerun (%s)' % (tid, e))
        return
    if diffs:
        P.append('[POWER-RERUN] tests.json: %s: rerunning the robust simulation gives other numbers (%s); write it with sim.py robust'
                 % (tid, '; '.join(diffs[:3])))
    elif rb.get('power_min', 1) < 0.8 or rb.get('false_positive_max', 0) > 0.10:
        W.append('[POWER-LOW] tests.json: %s: under the perturbed assumptions the power falls to %.3f and the false positives rise to '
                 '%.3f (targets: power 0.8 or more, false positives 0.10 or less): enlarge n, narrow the claim, or say so on the card'
                 % (tid, rb['power_min'], rb['false_positive_max']))


def check_decisive(work, data, ck, P):
    intake = data.get('intake.json')
    reco = data.get('recommendation.json') or {}
    claims_file = Path(work) / 'decisive_claims.json'
    ids = {t.get('id') for t in (data.get('tests.json') or {}).get('tests') or [] if isinstance(t, dict)}
    claims = []
    vp = ck.vp_mode(data) == 'vp'
    if claims_file.exists():
        try:
            cj = json.loads(claims_file.read_text(encoding='utf-8'))
            claims = [c for c in cj.get('claims') or [] if isinstance(c, dict)]
        except (ValueError, AttributeError):
            P.append('[DECISIVE] decisive_claims.json: not valid JSON')
    elif vp:
        P.append('[DECISIVE] decisive_claims.json: required with VP: every claim that decides (prior art, expected effect, verdict) '
                 'is linked to the passage VP verified')
    for c in claims:
        cid = c.get('id', '?')
        if c.get('decides') not in ('prior_art', 'expected_effect', 'verdict'):
            P.append('[DECISIVE] decisive_claims.json %s: decides must be prior_art, expected_effect or verdict' % cid)
        if c.get('supports') not in ('full', 'partial', 'context_only'):
            P.append('[DECISIVE] decisive_claims.json %s: supports must be full, partial or context_only' % cid)
        if c.get('decides') == 'verdict' and c.get('supports') == 'context_only':
            P.append('[DECISIVE] decisive_claims.json %s: a context-only passage cannot carry the verdict' % cid)
        for f, n in (('claim', 15), ('scope', 20), ('limits', 20), ('why_linked', 40)):
            if common.is_placeholder(c.get(f), n):
                P.append('[DECISIVE] decisive_claims.json %s: %s is empty or too short (%d characters or more)' % (cid, f, n))
        ref = c.get('ref') if isinstance(c.get('ref'), dict) else None
        if vp and ref is not None:
            _, code, msg = ck.ref_check(ck.VPRuns(work, intake), ref)
            if code:
                P.append('[DECISIVE-FRAGMENT] decisive_claims.json %s: %s %s' % (cid, code, msg))
                continue
            v = vp_claim(work, intake, ref.get('run'), ref.get('claim'))
            if v is None or not fragment_ok(c.get('fragment'), v['fragments']):
                P.append('[DECISIVE-FRAGMENT] decisive_claims.json %s: the fragment is not one that VP verified for claim %s'
                         % (cid, ref.get('claim')))
            elif c.get('supports') == 'full':
                missing = [n for n in NUM.findall(text(c.get('claim'))) if n not in text(c.get('fragment'))]
                if missing:
                    P.append('[DECISIVE-OVERCLAIM] decisive_claims.json %s: supports "full" but %s of the claim is not in the '
                             'fragment: FOUND does not make a wider claim verified (use "partial")' % (cid, ', '.join(missing)))
        elif vp:
            P.append('[DECISIVE-FRAGMENT] decisive_claims.json %s: ref = {id, run, claim} of a VP run is required' % cid)
    just = reco.get('justification') if isinstance(reco, dict) else None
    known = {c.get('id') for c in claims} | ids
    if (not isinstance(just, dict) or not isinstance(just.get('from'), list) or not just['from']
            or any(x not in known for x in just['from']) or common.is_placeholder(just.get('link'), 30)):
        P.append('[DECISIVE] recommendation.json: justification = {from: [ids of decisive claims or tests], link} is required: the '
                 'verdict states how those results lead to the conclusion')


def check_coverage(work, data, ck, P):
    pa = data.get('prior_art.json')
    intake = data.get('intake.json')
    reco = data.get('recommendation.json') or {}
    if isinstance(pa, dict) and ck.vp_mode(data) == 'vp':
        runs = ((intake or {}).get('vp') or {}).get('runs') or {}
        path = runs.get('prior_art')
        if isinstance(path, str):
            d = Path(path)
            d = d if d.is_absolute() else Path(work) / d
            if pa.get('coverage') != guards.coverage(d):
                P.append('[COVER-STALE] prior_art.json: coverage is missing or differs from the gateway journal of the VP run '
                         '(python3 -I <SKILL_DIR>/tools/guards.py coverage-write <dir>); it is computed, never typed')
    fields = [('recommendation.json reason', reco.get('reason'))]
    if isinstance(pa, dict):
        fields.append(('prior_art.json searched', pa.get('searched')))
        for i, c in enumerate(pa.get('closest_work') or []):
            if isinstance(c, dict):
                fields.append(('prior_art.json closest_work[%d].what_differs' % i, c.get('what_differs')))
    for where, s in fields:
        s = text(s)
        if RECALL.search(s) and not re.search(r'recall (?:is )?unknown|rappel (?:est )?inconnu', s, re.I):
            P.append('[RECALL-CLAIM] %s: no recall is claimed: it is unknown without an independent reference; say what the search '
                     'covered (calls, caps, sources) instead' % where)


def check_hybrid(work, data, ck, P, W=None):
    """Exact reuse checks, plus advisory partial matches.

    Standalone callers omitting W receive all diagnostics in P; run() supplies
    W so possible reuse is always a mark, in every directory version.
    """
    fp = Path(work) / 'free_draft.md'
    cj = data.get('draft_claims.json')
    if not fp.exists() or not isinstance(cj, dict):
        return
    intake = data.get('intake.json')
    draft = fp.read_text(encoding='utf-8')
    claims = [c for c in cj.get('claims') or [] if isinstance(c, dict)]
    for c in claims:
        if c.get('status') != 'verified' or not isinstance(c.get('ref'), dict):
            continue
        sp = c.get('support') if isinstance(c.get('support'), dict) else {}
        v = vp_claim(work, intake, c['ref'].get('run'), c['ref'].get('claim'))
        bad = None
        if any(common.is_placeholder(sp.get(f), n) for f, n in (('proposition', 10), ('link', 30), ('scope', 10))):
            bad = 'support = {proposition, fragment, link, scope} is required: the verifier shows how its passage supports the whole claim'
        elif v is None or not fragment_ok(sp.get('fragment'), v['fragments']):
            bad = 'support.fragment is not a fragment that VP verified for that claim'
        else:
            miss = [n for n in NUM.findall(text(sp.get('proposition'))) if n not in text(sp.get('fragment'))]
            if miss:
                bad = 'the proposition says %s, which the fragment does not' % ', '.join(miss)
        if bad:
            P.append('[DRAFT-SUPPORT] draft_claims.json %s: %s' % (c.get('id'), bad))
    rows = hybrid.analyse(draft, claims, data, strict=True)
    by_id = {c.get('id'): c for c in claims}
    for row in rows:
        possible = row.get('possible_reuse_in', [])
        if possible:
            message = '[DRAFT-REUSE?] possible reuse of draft item %r in %s: verify the correspondence; '
            message += 'a partial lexical match does not establish agreement or transfer source verification'
            message %= (row['text'], ', '.join(sorted({'%s %s' % (t['file'], t['path']) for t in possible})))
            (P if W is None else W).append(message if W is None else 'mark: ' + message)
        decisive = [t for t in row['taken_up_in'] if t['file'] in ('recommendation.json',) or
                    (t['file'] == 'tests.json' and '.decision_rule.' in '.' + t['path'] + '.')]
        cov = [by_id[i] for i in row['covered_by'] if i in by_id]
        if not row['taken_up_in']:
            continue
        if not cov:
            P.append('[DRAFT-UNMARKED] the draft item %r is taken up in %s but no claim quotes its whole sentence: verify it, '
                     'mark it "unverified (memory)" or remove it' % (row['text'], ', '.join(sorted({t['file'] for t in row['taken_up_in']}))))
        elif decisive and all(c.get('status') == 'unverified_memory' for c in cov) and any(not t['marked'] for t in decisive):
            P.append('[DRAFT-DECISIVE] the draft item %r decides (%s) but is only "unverified (memory)" and the deciding text does '
                     'not carry that mark' % (row['text'], ', '.join(sorted({t['file'] for t in decisive}))))


def check_provenance(work, data, W, P):
    rels = []
    for it in (data.get('material.json') or {}).get('items') or []:
        if isinstance(it, dict) and it.get('via') == 'gateway' and isinstance(it.get('envelope'), str):
            rels.append(it['envelope'])
    for s in (data.get('material.json') or {}).get('searched') or []:
        if isinstance(s, dict) and isinstance(s.get('envelope'), str):
            rels.append(s['envelope'])
    for s in (data.get('moment.json') or {}).get('series') or []:
        if isinstance(s, dict) and isinstance(s.get('envelope'), str):
            rels.append(s['envelope'])
    seen = set()
    for rel in rels:
        if rel in seen or not (Path(work) / rel).is_file():
            continue
        seen.add(rel)
        st, why = guards.provenance(work, rel)
        if st == 'mismatch':
            P.append('[PROV-MISMATCH] %s: the gateway journal contradicts this saved answer (%s): the envelope was changed or is '
                     'not the one the gateway returned' % (rel, why))
        elif st != 'journal-attested':
            W.append('[PROV-UNVERIFIED] %s: unverified provenance (%s); shown as such, never as extracted' % (rel, why))


def run(work, data, P, W, ck):
    work = Path(work)
    r3 = guards.is_r3(work)
    arith(data.get('tests.json'), P, W, strict_n=r3)
    if not r3:
        return
    tj = data.get('tests.json')
    if not guards.is_v2(work):                      # v2 has "Next step" instead (tools/v2check.py [NEXT-STEP])
        check_tomorrow(data.get('recommendation.json'), tj, P)
    check_log_after(work, data, ck, P)
    check_fixes(work, data, ck, P, W)
    check_tests_r3(work, data, ck, P, W)
    check_decisive(work, data, ck, P)
    check_coverage(work, data, ck, P)
    check_hybrid(work, data, ck, P, W)
    check_provenance(work, data, W, P)
