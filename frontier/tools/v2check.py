#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Checks of Frontier v2 (regression specification). Called by tools/check.py; offline, no model. They apply to a directory of
frontier_version 4 only (intake.json, or the marker tools/new_run.py writes); a directory of an earlier round keeps its rules.

The rule of v2 (the framing of the project, PRIME): only factual, arithmetic, integrity and confidentiality errors block; what
is methodological is MARKED ("mark: [CODE] ..." in the output of tools/check.py and in "Marked, not blocking" on the card), so
that no lead disappears and the researcher decides.

BLOCKING
  [FRAMING]        framing.json missing, undecided, changed after the decision, or inconsistent with the decision (stage 1).
  [PLAN-MISSING] [PLAN-ITER] [PLAN-REVISION]   the iterative research plan: 2 to 3 iterations, fields with keywords, a real
                   revision between iterations, the reason to stop (stage 2).
  [PLAN-JOURNAL] [PLAN-ENVELOPE] [PLAN-FOUND] [PLAN-LEAK]   the plan's searches are in the gateway journal, their saved answers
                   are unchanged, every work "found" was returned, no keyword carries a word of the archives.
  [PLAN-PASSAGE] [PLAN-OUTCOME] [PLAN-COVER]   the four outcomes backed by a passage VP verified, coherent with prior_art.json,
                   no novelty note, coverage computed and never a recall.
  [FACETS] [OPERATOR]   facets of the idea; every rival and variant made by a named operator.
  [NAMED-VERIFY]   a "verified" dataset, model or metric whose evidence does not resolve (stage 3).
  [BELIEF-MISSING] [BELIEF-LOGIC]   belief_shift of every test: coherent redistribution between the competing hypotheses (stage 4).
  [VOI-MISSING] [VOI-ORDER]   voi levels and an order that follows information over cost.
  [CTX-USE]        a project number neither used by the simulation nor given a reasoned place (stage 4).
  [NEXT-STEP]      recommendation.json next_step = {test (the first of ranking.order), first_action} (stage 5).
  [REB-PLAN]       the iterative search of each neighbouring idea (stage 6).
MARKED (never blocking)
  [FRAMING-ORDER] [NAMED-LINK] [BELIEF-PRECISE] [HISTORY-NET]; and, in a v2 directory, the codes of SOFT below, raised by
  tools/check.py and r3check.py as problems in earlier rounds.
Import: run(work, data, P, W, ck); demote(P, W); OPERATORS; voi_ratio(voi); operator_label(op); stems(text)
"""
import fractions
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ written in the skill directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import framing  # noqa: E402
import guards  # noqa: E402
import named  # noqa: E402
import r3check  # noqa: E402
import research  # noqa: E402

# the library of named operators; "recurring ingredient" only for the three found again in independent systems
OPERATORS = {
    'facet_recombination': {'recurring_ingredient': True, 'what': 'keep the goal and change the mechanism, or the reverse; change the population or the evaluation'},
    'analogy': {'recurring_ingredient': True, 'what': 'the same goal-mechanism pair in another domain'},
    'literature_bridge': {'recurring_ingredient': True, 'what': 'an intermediate concept links the idea to a neighbouring field'},
    'anomaly': {'recurring_ingredient': False, 'what': 'explain an anomaly or contradiction found in the prior art'},
    'revived_old_idea': {'recurring_ingredient': False, 'what': 'an old idea on the same subject that the researcher\'s own tools list'},
    'hypothesis_inversion': {'recurring_ingredient': False, 'what': 'invert a hypothesis of the idea'},
    'morphological_analysis': {'recurring_ingredient': False, 'what': 'enumerate the combinations of the parts of the idea'},
    'new_problem': {'recurring_ingredient': False, 'what': 'define a new problem that the idea makes visible'},
    'new_hypothesis': {'recurring_ingredient': False, 'what': 'propose another hypothesis for the same observation'},
    'limits_exploration': {'recurring_ingredient': False, 'what': 'explore the limits of the current methods'},
    'critical_experiment': {'recurring_ingredient': False, 'what': 'design an experiment that one explanation alone can pass'},
    'rival_theories': {'recurring_ingredient': False, 'what': 'compare rival theories of the same phenomenon'}}
FACETS = ('goal', 'mechanism', 'population', 'evaluation', 'assumption')
STATUSES = ('Exists', 'Partially', 'Not found', 'Insufficient search')
ANSWER_TO_STATUS = {'Exists': ('Exists',), 'Partially': ('Partially',), 'Not found': ('Not found', 'Insufficient search')}
LEVELS = {'low': 1, 'medium': 2, 'high': 3}
MOVES = ('up', 'down', 'flat')
LEAK = {'archive-passage', 'archive-word', 'draft-passage'}
# the codes that earlier rounds raise as problems and that v2 only marks (the rest keeps blocking)
SOFT = ('[DRAFT-PRIORITY]', '[DRAFT-INVENTORY]', '[DRAFT-VERDICT]', '[DRAFT-RETAIN]',
        '[FIX-PROOF]', '[FIX-UNCONFIRMED]', '[RECO-OPEN]', '[DATA-SEEN]', '[SCOPE]', '[DRAFT-DECISIVE]', '[DRAFT-UNMARKED]',
        '[POWER-MISSING]', '[POWER-FIELD]', '[POWER-TARGET]', '[POWER-RANGE]')
PRECISE = re.compile(r'\b\d{1,3}(?:[.,]\d+)?\s?%|\bprobabilit\w*\s*(?:of|is|=|:)?\s*\d|\bp\s*=\s*0?[.,]\d|\blikelihood\s*(?:of|=|:)\s*\d', re.I)
STOP = r3check.STOPW | frozenset('after first again already based using tests trial trials result results classed rejected reopen '
                                 'verdict closed tried should would could their there these those'.split())


def text(x):
    return x.strip() if isinstance(x, str) else ''


def mark(W, code, msg):
    W.append('mark: %s %s' % (code, msg))


def operator_label(op):
    lib = OPERATORS.get(op)
    if lib is None:
        return str(op)
    return '%s (%s)' % (op, 'recurring ingredient' if lib['recurring_ingredient'] else 'operator not measured')


def voi_ratio(voi):
    """Ordinal information / cost as an exact fraction (high/high equals medium/medium)."""
    return fractions.Fraction(LEVELS[voi['information']], LEVELS[voi['cost']])


def stems(s):
    out = set()
    for w in common.words(str(s)):
        w = common.fold(w)
        if len(w) >= 5 and w not in STOP:
            out.add(w[:-1] if w.endswith('s') and len(w) > 5 else w)
    return out


def read(work, name):
    p = Path(work) / name
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def tests_of(data):
    tj = data.get('tests.json')
    return [t for t in (tj.get('tests') if isinstance(tj, dict) else None) or [] if isinstance(t, dict)]


# ---------------------------------------------------------------- stage 1: framing


def check_framing(work, data, P, W):
    f = read(work, 'framing.json')
    if not isinstance(f, dict):
        P.append('[FRAMING] framing.json: required in a v2 directory (python3 -I <SKILL_DIR>/tools/framing.py propose, then approve, '
                 'correct or assume)')
        return
    prop = f.get('proposal') if isinstance(f.get('proposal'), dict) else {}
    for m in framing.field_problems(prop):
        P.append('[FRAMING] framing.json proposal: %s' % m)
    if f.get('proposal_sha256') != framing.proposal_sha(prop):
        P.append('[FRAMING] framing.json: the proposal no longer matches its SHA-256 (it was changed after it was written)')
    ap = f.get('approval')
    if not isinstance(ap, dict) or ap.get('status') not in ('approved', 'corrected', 'assumption'):
        P.append('[FRAMING] framing.json: the framing has not been approved, corrected or assumed (tools/framing.py)')
    else:
        final = f.get('final') if isinstance(f.get('final'), dict) else {}
        for m in framing.field_problems(final):
            P.append('[FRAMING] framing.json final: %s' % m)
        st = ap.get('status')
        if st in ('approved', 'corrected'):
            if ap.get('by') != 'user' or len(text(ap.get('reply'))) < 3:
                P.append('[FRAMING] framing.json: an %s framing needs by "user" and the user\'s reply kept word for word' % st)
        elif ap.get('by') != 'assumption' or not text(ap.get('reply')).startswith('ASSUMED'):
            P.append('[FRAMING] framing.json: an assumed framing is marked ASSUMED, by "assumption"; it is never an approval')
        differ = [k for k in framing.FIELDS if final.get(k) != prop.get(k)]
        if st in ('approved', 'assumption') and differ:
            P.append('[FRAMING] framing.json: an %s framing equals the proposal, but %s differ' % (st, ', '.join(differ)))
        if st == 'corrected' and (not differ or sorted(ap.get('changes') or []) != sorted(differ)):
            P.append('[FRAMING] framing.json: a corrected framing lists the fields it changed (%s)' % ', '.join(differ) if differ
                     else '[FRAMING] framing.json: a corrected framing must change at least one field')
    dirs = [d for d in (data.get('intake.json') or {}).get('project_dirs') or [] if isinstance(d, str) and d.strip()]
    arch = f.get('archives') if isinstance(f.get('archives'), dict) else {}
    if arch.get('checked') is not bool(dirs):
        P.append('[FRAMING] framing.json: archives.checked is %r but project_dirs %s given: "checked" only with folders, '
                 '"not checked" otherwise' % (arch.get('checked'), 'is' if dirs else 'is not'))
    if not isinstance(f.get('free_phase'), dict) or not (f['free_phase'].get('draft') or text(f['free_phase'].get('skipped'))):
        P.append('[FRAMING] framing.json: free_phase says which free draft came first, or why there was none')
    rj = read(work, 'run.json')
    steps = [s.get('step') for s in (rj.get('steps') if isinstance(rj, dict) else None) or [] if isinstance(s, dict)]
    gated = [i for i, s in enumerate(steps) if s in ('vp_run', 'prior_art', 'hypotheses', 'tests', 'critique', 'research_plan')]
    if 'framing' not in steps:
        mark(W, '[FRAMING-ORDER]', 'run.json has no "framing" step (tools/step.py --step framing)')
    elif gated and steps.index('framing') > gated[0]:
        mark(W, '[FRAMING-ORDER]', 'run.json: the "framing" step comes after %s' % steps[gated[0]])


# ---------------------------------------------------------------- stage 2: research plan


def field_problems(it, k, cfg):
    out = []
    fields = [f for f in it.get('fields') or [] if isinstance(f, dict)]
    need = cfg['fields_min'] if k == 0 else 1
    if len(fields) < need:
        out.append('iteration %s needs at least %d field(s) to question, with the keywords of each' % (it.get('n'), need))
    for f in fields:
        if common.is_placeholder(f.get('field'), 3):
            out.append('iteration %s: a field has no name' % it.get('n'))
        if common.is_placeholder(f.get('why'), 20):
            out.append('iteration %s, field %r: why this field is questioned (20 characters or more)' % (it.get('n'), f.get('field')))
        kws = [x for x in f.get('keywords') or [] if isinstance(x, str) and x.strip()]
        if len(kws) < cfg['keywords_min']:
            out.append('iteration %s, field %r: at least %d keywords' % (it.get('n'), f.get('field'), cfg['keywords_min']))
    return out


def plan_signature(it):
    return {(text(f.get('field')).lower(), text(k).lower()) for f in it.get('fields') or [] if isinstance(f, dict)
            for k in f.get('keywords') or [] if isinstance(k, str)}


def check_plan(work, data, P, W, ck):
    plan = read(work, 'research_plan.json')
    if not isinstance(plan, dict):
        P.append('[PLAN-MISSING] research_plan.json: required in a v2 directory: the fields to question, the keywords of each, '
                 '2 to 3 iterations, the outcome (SKILL.md "Frontier v2: the path", stage 2)')
        return
    cfg = common.config()['research']
    its = [i for i in plan.get('iterations') or [] if isinstance(i, dict)]
    out = plan.get('outcome') if isinstance(plan.get('outcome'), dict) else {}
    status = out.get('status')
    vp = ck.vp_mode(data) == 'vp'
    intake = data.get('intake.json') or {}
    if len(its) > cfg['iterations_max']:
        P.append('[PLAN-ITER] research_plan.json: %d iterations, more than %d (a third round already saturates; stop and say why)'
                 % (len(its), cfg['iterations_max']))
    if len(its) < cfg['iterations_min'] and status != 'Insufficient search':
        P.append('[PLAN-ITER] research_plan.json: %d iteration(s): do a second plan-search-revision round, or declare the outcome '
                 '"Insufficient search"' % len(its))
    for k, it in enumerate(its):
        for m in field_problems(it, k, cfg):
            P.append('[PLAN-ITER] research_plan.json: %s' % m)
        if k < len(its) - 1:
            rev = it.get('revision') if isinstance(it.get('revision'), dict) else {}
            if common.is_placeholder(rev.get('learned'), 20) or not [c for c in rev.get('changes') or [] if text(c)]:
                P.append('[PLAN-REVISION] research_plan.json iteration %s: the revision says what was learned (20 characters or '
                         'more) and what changes in the next plan (at least one change)' % it.get('n'))
            if plan_signature(it) == plan_signature(its[k + 1]):
                P.append('[PLAN-REVISION] research_plan.json: iteration %s has the same fields and keywords as iteration %s: a '
                         'plan that does not change is not an iteration' % (its[k + 1].get('n'), it.get('n')))
        elif common.is_placeholder(it.get('stop_reason'), 20):
            P.append('[PLAN-REVISION] research_plan.json iteration %s: the last iteration says why the search stops (stop_reason)'
                     % it.get('n'))
        # keywords never carry the archives
        for f in it.get('fields') or []:
            if isinstance(f, dict):
                for kw in [f.get('field')] + list(f.get('keywords') or []):
                    if isinstance(kw, str) and kw.strip() and set(guards.check_outgoing(work, kw)) & LEAK:
                        P.append('[PLAN-LEAK] research_plan.json iteration %s: %r holds a word or a passage of your archives or '
                                 'of the free draft: write the keywords from the idea' % (it.get('n'), kw))
        # the calls
        calls = [c for c in it.get('calls') or [] if isinstance(c, dict)]
        if vp and not calls:
            P.append('[PLAN-JOURNAL] research_plan.json iteration %s: no search went through the gateway (tools/research.py search)' % it.get('n'))
        journal = [e for e in guards_journal(work)]
        used = {}
        ids = set()
        for c in calls:
            fld = next((f for f in it.get('fields') or [] if isinstance(f, dict) and f.get('field') == c.get('field')), None)
            if fld is None or not research.keyword_used(c.get('query', ''), fld.get('keywords') or []):
                P.append('[PLAN-ITER] research_plan.json iteration %s: the query %r uses no keyword of its field as planned'
                         % (it.get('n'), c.get('query')))
            q = text(c.get('query'))
            hits = [e for e in journal if e.get('call') == c.get('command') and e.get('query') == q and e.get('T') == intake.get('T')
                    and e.get('run') == research.RUN]
            used[q] = used.get(q, 0) + 1
            if len(hits) < used[q]:
                P.append('[PLAN-JOURNAL] research_plan.json iteration %s: the search %r has no entry in research/state/journal.jsonl '
                         '(the gateway journals every call; a search typed by hand does not count)' % (it.get('n'), q))
            p = Path(work) / text(c.get('envelope'))
            env = read(work, text(c.get('envelope'))) if p.is_file() and 'matter' in p.parts else None
            if env is None or common.sha256_file(p) != c.get('envelope_sha256'):
                P.append('[PLAN-ENVELOPE] research_plan.json iteration %s: the saved answer %r is missing or was changed'
                         % (it.get('n'), c.get('envelope')))
            elif research.extract_ids(env.get('gateway')) != c.get('ids'):
                P.append('[PLAN-ENVELOPE] research_plan.json iteration %s: the ids recorded for %r are not those of the saved answer'
                         % (it.get('n'), q))
            else:
                ids.update(x.lower() for x in c.get('ids') or [])
        if calls:
            for fd in it.get('found') or []:
                if isinstance(fd, dict) and text(fd.get('id')).lower() not in ids:
                    P.append('[PLAN-FOUND] research_plan.json iteration %s: %r was not returned by any search of this iteration'
                             % (it.get('n'), fd.get('id')))
    # outcome
    if status not in STATUSES:
        P.append('[PLAN-OUTCOME] research_plan.json: outcome.status must be one of %s' % ', '.join(STATUSES))
    pa = data.get('prior_art.json') or {}
    allowed = ANSWER_TO_STATUS.get(pa.get('answer'))
    if status in STATUSES and allowed and status not in allowed:
        P.append('[PLAN-OUTCOME] research_plan.json: the outcome %r does not agree with the answer %r of prior_art.json (the answer '
                 'is never raised; only "Not found" may be lowered to "Insufficient search")' % (status, pa.get('answer')))
    if status in ('Exists', 'Partially'):
        ps = out.get('passage') if isinstance(out.get('passage'), dict) else None
        ref = ps.get('ref') if ps else None
        if not ps or not isinstance(ref, dict) or common.is_placeholder(ps.get('fragment'), 8):
            P.append('[PLAN-PASSAGE] research_plan.json: an outcome %r rests on a passage {ref, fragment} of the closest work' % status)
        elif vp:
            _, code, msg = ck.ref_check(ck.VPRuns(work, intake), ref)
            v = r3check.vp_claim(work, intake, ref.get('run'), ref.get('claim'))
            if code:
                P.append('[PLAN-PASSAGE] research_plan.json: %s %s' % (code, msg))
            elif v is None or not r3check.fragment_ok(ps.get('fragment'), v['fragments']):
                P.append('[PLAN-PASSAGE] research_plan.json: the fragment is not one that VP verified for claim %s' % ref.get('claim'))
        else:
            mark(W, '[PLAN-PASSAGE]', 'research_plan.json: not verified: no VP, the passage is as the host wrote it')
        if status == 'Partially' and common.is_placeholder(out.get('difference'), 20):
            P.append('[PLAN-OUTCOME] research_plan.json: "Partially" shows the exact difference (outcome.difference)')
    if status in ('Not found', 'Insufficient search') and common.is_placeholder(out.get('summary'), 20):
        P.append('[PLAN-OUTCOME] research_plan.json: outcome.summary says what was searched and what that does not show')
    ss = plan.get('scope_split')
    if ss is not None:
        if not isinstance(ss, dict) or any(ss.get(k) not in STATUSES for k in ('whole_field', 'cited_by_idea')):
            P.append('[PLAN-OUTCOME] research_plan.json: scope_split = {whole_field, cited_by_idea}, each one of %s' % ', '.join(STATUSES))
    for key in _score_keys(plan):
        P.append('[PLAN-OUTCOME] research_plan.json: field %r reads as a novelty or interest note; prior art has four outcomes and no score' % key)
    for s in r3check.strings(plan):
        c = ck.CERTIFY.search(s) or ck.SCORE_TEXT.search(s)
        if c:
            P.append('[PLAN-OUTCOME] research_plan.json: %r certifies or scores novelty; "Not found" is never "new"' % c.group(0))
    if r3check.RECALL.search(' '.join(text(out.get(k)) for k in ('summary', 'difference'))):
        P.append('[RECALL-CLAIM] research_plan.json: outcome text claims a recall; the recall is unknown (no independent reference)')
    # coverage: computed from the gateway journal, never typed
    if vp or any(i.get('calls') for i in its):
        if plan.get('coverage') != research.coverage_of(work, plan):
            P.append('[PLAN-COVER] research_plan.json: coverage is missing or differs from the gateway journal (python3 -I '
                     '<SKILL_DIR>/tools/research.py coverage <dir>); it is computed, never typed, and never a recall')


def guards_journal(work):
    out = []
    p = Path(work) / 'research' / 'state' / 'journal.jsonl'
    try:
        for line in p.read_text(encoding='utf-8').splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict):
                out.append(e)
    except OSError:
        pass
    return out


def _score_keys(x, path=''):
    out = []
    if isinstance(x, dict):
        for k, v in x.items():
            if re.search(r'novel|origin|score|rating|grade|interest|promis', str(k), re.I) and not isinstance(v, (dict, list, str)) and v is not None:
                out.append(k)
            out += _score_keys(v)
    elif isinstance(x, list):
        for v in x:
            out += _score_keys(v)
    return out


# ---------------------------------------------------------------- stage 3: facets, operators, named elements


def check_hypotheses_v2(work, data, P, W):
    hy = data.get('hypotheses.json')
    if not isinstance(hy, dict):
        return
    fc = hy.get('facets')
    if not isinstance(fc, dict) or any(common.is_placeholder(fc.get(k), 20) for k in ('goal', 'mechanism')):
        P.append('[FACETS] hypotheses.json: facets = {goal, mechanism} (20 characters or more each; population and evaluation '
                 'optional): the idea cut into what it wants and how')
    else:
        for k in ('population', 'evaluation'):
            if k in fc and common.is_placeholder(fc.get(k), 10):
                P.append('[FACETS] hypotheses.json: facets.%s is a placeholder' % k)
    for key in ('rivals', 'repairable_variants'):
        for it in hy.get(key) or []:
            if not isinstance(it, dict):
                continue
            if it.get('operator') not in OPERATORS:
                P.append('[OPERATOR] hypotheses.json %s: operator must be one of %s (a rival or a variant comes from a named '
                         'operator)' % (it.get('id'), ', '.join(sorted(OPERATORS))))
            if it.get('facet') not in FACETS:
                P.append('[OPERATOR] hypotheses.json %s: facet must be one of %s (the facet the operator changes)' % (it.get('id'), ', '.join(FACETS)))


def check_named(work, data, P, W, ck):
    nj = read(work, 'named_elements.json')
    els = [e for e in (nj.get('elements') if isinstance(nj, dict) else None) or [] if isinstance(e, dict)]
    ids = {e.get('id') for e in els}
    if len(ids) != len(els):
        P.append('[NAMED-VERIFY] named_elements.json: duplicate element ids')
    material = read(work, 'material.json')
    for e in els:
        if e.get('kind') not in named.KINDS:
            P.append('[NAMED-VERIFY] named_elements.json %s: kind must be one of %s' % (e.get('id'), ', '.join(named.KINDS)))
        why = named.element_problem(work, data.get('intake.json') or {}, material, e, ck)
        if why:
            P.append('[NAMED-VERIFY] named_elements.json %s (%s): %s' % (e.get('id'), e.get('name'), why))
    for t in tests_of(data):
        tid = t.get('id')
        listed = t.get('named_elements')
        if isinstance(listed, list):
            for i in listed:
                if i not in ids:
                    P.append('[NAMED-VERIFY] tests.json %s: names the element %r, which is not in named_elements.json' % (tid, i))
        elif common.is_placeholder(t.get('named_elements_none'), 20):
            mark(W, '[NAMED-LINK]', 'tests.json %s: lists no named_elements and gives no named_elements_none: which datasets, models '
                                    'and metrics does it use, and do they exist?' % tid)
        body = '\n'.join(s for k, v in t.items() if k not in ('named_elements', 'named_elements_none', 'internal_history')
                         for s in r3check.strings(v)).lower()
        for e in els:
            nm = text(e.get('name')).lower()
            if len(nm) >= 4 and nm in body and e.get('id') not in (listed if isinstance(listed, list) else []):
                mark(W, '[NAMED-LINK]', 'tests.json %s: the text names %r (%s) but the test does not list it in named_elements'
                     % (tid, e.get('name'), e.get('id')))


# ---------------------------------------------------------------- stage 4: belief shift, value of information, project numbers


def check_belief(t, P, W):
    tid, comp = t.get('id'), [c for c in t.get('competing_hypotheses') or [] if isinstance(c, str)]
    bs = t.get('belief_shift')
    if not isinstance(bs, dict) or not isinstance(bs.get('outcomes'), list) or not bs['outcomes']:
        P.append('[BELIEF-MISSING] tests.json %s: belief_shift = {exclusive, before, outcomes} is required: what each outcome does to '
                 'the belief between the competing hypotheses' % tid)
        return
    if not isinstance(bs.get('exclusive'), bool):
        P.append('[BELIEF-LOGIC] tests.json %s: belief_shift.exclusive must be true or false (can the explanations hold together?)' % tid)
    excl = bs.get('exclusive') is True
    outs = [o for o in bs['outcomes'] if isinstance(o, dict)]
    ok = True
    for o in outs:
        mv = o.get('moves')
        if o.get('matches') not in comp + ['ambiguous', 'unexpected']:
            P.append('[BELIEF-LOGIC] tests.json %s: an outcome matches %r, which is neither a competing hypothesis nor "ambiguous" '
                     'or "unexpected"' % (tid, o.get('matches')))
            ok = False
        if not isinstance(mv, dict) or set(mv) != set(comp) or any(v not in MOVES for v in mv.values()):
            P.append('[BELIEF-LOGIC] tests.json %s: moves must give up, down or flat for exactly %s (no number)' % (tid, ', '.join(comp)))
            ok = False
    if not ok:
        return
    for x in comp:
        mine = [o for o in outs if o['matches'] == x]
        if not mine:
            P.append('[BELIEF-LOGIC] tests.json %s: no outcome where %s is the one the result matches' % (tid, x))
        for o in mine:
            others = [v for k, v in o['moves'].items() if k != x]
            if o['moves'][x] != 'up':
                P.append('[BELIEF-LOGIC] tests.json %s: when the result matches %s, %s must go up' % (tid, x, x))
            elif excl and ('up' in others or 'down' not in others):
                P.append('[BELIEF-LOGIC] tests.json %s: the explanations exclude each other, so when %s goes up another goes down '
                         'and none goes up with it' % (tid, x))
    amb = [o for o in outs if o['matches'] == 'ambiguous']
    if not amb:
        P.append('[BELIEF-LOGIC] tests.json %s: an "ambiguous" outcome (the overlap of the predictions) is required' % tid)
    for o in amb:
        if any(v != 'flat' for v in o['moves'].values()):
            P.append('[BELIEF-LOGIC] tests.json %s: an ambiguous outcome does not discriminate: every move is flat' % tid)
    if not [o for o in outs if o['matches'] == 'unexpected']:
        mark(W, '[BELIEF-MISSING]', 'tests.json %s: no "unexpected" outcome (what to do if no hypothesis predicted the result)' % tid)
    for s in [bs.get('before')] + [x for o in outs for x in (o.get('then'), o.get('outcome'))]:
        m = PRECISE.search(text(s))
        if m:
            mark(W, '[BELIEF-PRECISE]', 'tests.json %s: %r reads as a probability; the belief moves in scenarios, without a falsely '
                                        'precise number' % (tid, m.group(0)))


def check_voi(data, P, W):
    tests = tests_of(data)
    ok = {}
    for t in tests:
        v = t.get('voi')
        if (not isinstance(v, dict) or v.get('information') not in LEVELS or v.get('cost') not in LEVELS
                or common.is_placeholder(v.get('why'), 30)):
            P.append('[VOI-MISSING] tests.json %s: voi = {information, cost (low|medium|high), why (30 characters or more)} is required'
                     % t.get('id'))
        else:
            ok[t.get('id')] = voi_ratio(v)
    rk = (data.get('tests.json') or {}).get('ranking') or {}
    order = [x for x in rk.get('order') or [] if x in ok]
    inversions = [(a, b) for i, a in enumerate(order) for b in order[i + 1:] if ok[a] < ok[b]]
    if inversions and common.is_placeholder(rk.get('order_exception'), 30):
        P.append('[VOI-ORDER] tests.json ranking.order puts %s before %s although the second has more information per unit of cost: '
                 'reorder, or write ranking.order_exception (30 characters or more)' % inversions[0])


def usable_numbers(intake):
    ctx = intake.get('context') if isinstance(intake, dict) else None
    return [k for k in (ctx.get('key_numbers') if isinstance(ctx, dict) else None) or []
            if isinstance(k, dict) and isinstance(k.get('value'), (int, float)) and not isinstance(k.get('value'), bool)
            and (k.get('confirmed') is True or (k.get('source') == 'user' and k.get('confirmed') is not False))]


def context_roles(intake):
    return common.context_inputs(intake)


def check_context_use(data, P, W):
    intake = data.get('intake.json') or {}
    nums = usable_numbers(intake)
    if not nums:
        return
    ci = context_roles(intake)
    for t in tests_of(data):
        tag = 'tests.json %s' % t.get('id')
        sens = t.get('sensitivity') if isinstance(t.get('sensitivity'), dict) else {}
        sim = sens.get('simulation') if isinstance(sens.get('simulation'), dict) else None
        cb = (sim or {}).get('context') if isinstance((sim or {}).get('context'), dict) else {}
        inputs = cb.get('inputs') if cb.get('used') is True and isinstance(cb.get('inputs'), dict) else {}
        power = sens.get('power') if isinstance(sens.get('power'), dict) else {}
        uses = {u.get('name'): u for u in power.get('context_use') or [] if isinstance(u, dict)}
        names = {k.get('name') for k in nums}
        freed = set()
        for k in nums:
            nm = k.get('name')
            in_sim = any(isinstance(i, dict) and i.get('name') == nm and (sim or {}).get(role) == k.get('value') for role, i in inputs.items())
            u = uses.get(nm)
            if in_sim:
                continue
            if u is None:
                P.append('[CTX-USE] %s: the project number %s = %s is neither used by the simulation nor given a place in '
                         'sensitivity.power.context_use: use it (tools/sim.py --context), or say why it is not a simulation input'
                         % (tag, nm, k.get('value')))
            elif u.get('use') != 'not_a_simulation_input' or common.is_placeholder(u.get('why'), 30):
                P.append('[CTX-USE] %s: the project number %s is said to be a simulation input or has a vague reason, and the '
                         'simulation does not use it: give a reason of 30 characters or more' % (tag, nm))
            else:
                freed.add(nm)
        for nm in uses:
            if nm not in names:
                P.append('[CTX-USE] %s: context_use names %r, which is not a usable key number of the context' % (tag, nm))
        for p in power.get('parameters') or []:
            if isinstance(p, dict) and p.get('status') == 'assumed':
                for role, c in ci.items():
                    if (p.get('name') == role or p.get('name') in common.ROLE_NAMES[role]) and c['name'] not in freed \
                            and role not in inputs:
                        P.append('[CTX-USE] %s: the parameter %s is "assumed" although the project gives %s = %s' % (tag, p.get('name'), c['name'], c['value']))
                        break


def check_tests_v2(work, data, P, W):
    for t in tests_of(data):
        check_belief(t, P, W)
    check_voi(data, P, W)
    check_context_use(data, P, W)


def check_next_step(data, P):
    reco = data.get('recommendation.json') or {}
    ns = reco.get('next_step')
    order = ((data.get('tests.json') or {}).get('ranking') or {}).get('order') or []
    if not isinstance(ns, dict):
        P.append('[NEXT-STEP] recommendation.json: next_step = {test, first_action} is required (the first gesture, on top of the card)')
        return
    if not order or ns.get('test') != order[0]:
        P.append('[NEXT-STEP] recommendation.json: next_step.test is %r but the first test of ranking.order is %r' % (ns.get('test'), order[:1]))
    if common.is_placeholder(ns.get('first_action'), 30):
        P.append('[NEXT-STEP] recommendation.json: next_step.first_action must say the first gesture (30 characters or more)')


# ---------------------------------------------------------------- stage 5/6: the project's own history, said at the head


def history_net(work, data, W, ck):
    """[HISTORY-NET]: a test or idea that shares content words with a CLASSED passage of the project's archives, whatever terms the
    host chose, and that neither cites nor removes it. A mark, at the head of the item on the card."""
    hist = read(work, 'history.json')
    dirs = ck.project_dirs(data.get('intake.json'))
    if not dirs or not isinstance(hist, dict):
        return []
    idx = ck.HistoryIndex(hist, work, dirs)
    out = []
    gen = {common.fold(g) for g in idx.generic_terms()}
    for fname, iid, obj, skip in ck.history_items(data):
        body = '\n'.join(ck._skip_strings(obj, skip + ('named_elements_none', 'belief_shift', 'voi')))
        mine = stems(body)
        cited = {it.get('entry') for it in obj.get('internal_history') or [] if isinstance(it, dict)}
        for e in idx.entries:
            if e.get('verdict') != 'classed' or e.get('id') in cited or idx.overlaps(e, iid, body):
                continue
            shared = sorted((stems('%s %s' % (e.get('excerpt'), e.get('verdict_excerpt') or '')) & mine) - gen)
            if len(shared) >= 3:
                out.append({'file': fname, 'id': iid, 'entry': e, 'shared': shared})
    for h in out:
        e = h['entry']
        mark(W, '[HISTORY-NET]', '%s %s shares %d content words (%s) with a trial your project classed: %s:%s [%s]: read it before '
                                 'relying on this' % (h['file'], h['id'], len(h['shared']), ', '.join(h['shared'][:6]), e.get('file'),
                                                      e.get('line'), ', '.join((e.get('markers') or [])[:3])))
    return out


def check_reb_plan(work, data, P, W, ck):
    for fname in ck.REBOUND_FILES:
        rb = data.get(fname)
        for i in (rb.get('ideas') if isinstance(rb, dict) else None) or []:
            if not isinstance(i, dict):
                continue
            tag = '%s %s' % (fname, i.get('id'))
            sp = i.get('search_plan')
            if not isinstance(sp, dict):
                P.append('[REB-PLAN] %s: search_plan = {iterations, differs_from_previous} is required in a v2 directory: the idea '
                         'comes from a plan-search-revision loop' % tag)
                continue
            cfg = common.config()['research']
            its = [x for x in sp.get('iterations') or [] if isinstance(x, dict)]
            if len(its) < cfg['iterations_min'] or len(its) > cfg['iterations_max']:
                P.append('[REB-PLAN] %s: search_plan has %d iteration(s), %d to %d are required' % (tag, len(its), cfg['iterations_min'], cfg['iterations_max']))
                continue
            for k, it in enumerate(its):
                for m in field_problems(dict(it, n=it.get('n', k + 1)), k, cfg):
                    P.append('[REB-PLAN] %s: %s' % (tag, m))
                if k < len(its) - 1:
                    rev = it.get('revision') if isinstance(it.get('revision'), dict) else {}
                    if common.is_placeholder(rev.get('learned'), 20) or not [c for c in rev.get('changes') or [] if text(c)]:
                        P.append('[REB-PLAN] %s: iteration %s has no revision (what was learned, what changes)' % (tag, k + 1))
                    if plan_signature(it) == plan_signature(its[k + 1]):
                        P.append('[REB-PLAN] %s: iteration %s repeats the fields and keywords of iteration %s: that is not an iteration' % (tag, k + 2, k + 1))
                for f in it.get('fields') or []:
                    if isinstance(f, dict):
                        for kw in [f.get('field')] + list(f.get('keywords') or []):
                            if isinstance(kw, str) and kw.strip() and set(guards.check_outgoing(work, kw)) & LEAK:
                                P.append('[REB-PLAN] %s: the keyword %r carries a word or passage of your archives' % (tag, kw))
            if common.is_placeholder(sp.get('differs_from_previous'), 30):
                P.append('[REB-PLAN] %s: differs_from_previous says how the revised idea differs from the previous version (30 characters or more)' % tag)
            last = its[-1]
            pa_q = {ck._norm_query(q) for q in ((i.get('prior_art') or {}).get('queries') or []) if isinstance(q, str)}
            qs = [q for q in last.get('queries') or [] if isinstance(q, str)]
            kws = [k for f in last.get('fields') or [] if isinstance(f, dict) for k in f.get('keywords') or []]
            if not qs or any(ck._norm_query(q) not in pa_q for q in qs):
                P.append('[REB-PLAN] %s: the queries of the last iteration are the queries of the prior-art check of the idea (prior_art.queries)' % tag)
            elif not all(research.keyword_used(q, kws) for q in qs):
                P.append('[REB-PLAN] %s: a query of the last iteration uses no keyword of its plan' % tag)


# ---------------------------------------------------------------- entry points


def run(work, data, P, W, ck):
    work = Path(work)
    if not guards.is_v2(work):
        return
    check_framing(work, data, P, W)
    check_plan(work, data, P, W, ck)
    check_hypotheses_v2(work, data, P, W)
    check_named(work, data, P, W, ck)
    check_tests_v2(work, data, P, W)
    check_next_step(data, P)
    history_net(work, data, W, ck)
    check_reb_plan(work, data, P, W, ck)


def demote(P, W):
    """In a v2 directory the methodological codes of SOFT do not block: they become marks (same text, "mark: " first)."""
    keep, moved = [], []
    for p in P:
        if p.startswith(SOFT):                 # the card lists a mark whole: no ellipsis may come out of a message
            moved.append('mark: ' + p.replace('[...]', '[a list]').replace('…', ' etc.').replace('...', ' etc.'))
        else:
            keep.append(p)
    return keep, moved + list(W)
