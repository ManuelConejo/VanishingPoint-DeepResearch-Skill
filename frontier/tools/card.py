#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Assemble IDEA-CARD.md, the one-page idea card, from the JSON files of a Frontier working directory (SKILL.md step 6,
and again at the end of step 7).

The card is written by this tool only, never by hand. It runs tools/check.py first and refuses (exit code 1, problems
printed, nothing written) when the directory does not pass. The card is then rendered in memory and checked as a card
(header, one page, inputs fingerprint); only a card that passes is written, to a temporary file renamed over
IDEA-CARD.md: an invalid card is never left on disk and never replaces a valid one.
Content, in this order: the Rebound disclaimer (tools/disclaimer.py), then the header
"References not verified (VP not installed)" when VP was not used, or "Unverified references: ..." when VP references
are UNVERIFIED or SOURCE-UNAVAILABLE; the recommendation
(dig / test first / drop) with its one-sentence reason and the statement that the card is not a certification of novelty
or value; the idea and the gain that would justify the effort; "Already tried here" (internal history, step 0-bis: the head
line says "not checked" when intake.json gives no project_dirs; otherwise a section lists the classed trials found in the
user's own archives with file:line, verdict markers, reopening condition and the test or idea that keeps or removed it;
never an excerpt of the archives beyond that); prior art (Exists / Partially / Not found, closest work and
what differs, materials); the load-bearing hypotheses, rivals and repairable variants with their references (with VP:
each reference followed by its VP verification status, e.g. [FOUND], [DISTORTED]; without VP: [unverified]); the tests in
ranking order, each with its grid in short form, the four traps and the L0 leakage control; the ranking scenarios; the
critique of the protocol (with "Critique: same family (no independent critic available)" when it applies) and the
critic's trap verdicts; the result or "Plan only"; the decision log; the neighbouring ideas of the rebound step (section
"Neighbouring ideas" from rebound.json, "Rebound after T" from rebound_after.json: one line per idea with its operator and
"not measured" when it is, its prior-art status with "already done: read, do not redo" for Exists and "not checked" when
the budget ran out, its feasibility with "not established" where it is, its cheapest test; the duplicate groups, the
researcher's choice and the first scenarios; no score; when the page is full, scenarios go first, then ideas "(+k more in
rebound.json)"); and, last, the fingerprint of the files the card was
assembled from (<!-- frontier inputs sha256:... -->), which tools/check.py compares with the files ([CARD-STALE]).
The free text comes from the JSON files, written in the user's language (intake.json "language"); the labels of the card
are fixed, in English. At most 80 lines including the disclaimer: long fields are shortened on the card, the full text
stays in the JSON files.

Usage: card.py DIR
       card.py --disclaimer [--lang fr]  (print only; optional DIR supplies intake.json language)
On success the first two lines of stdout are the paths of IDEA-CARD.md and
IDEA-REPORT.md, in that order, followed by the final-command reminder.
Read paths by position; do not assume stdout contains exactly two lines.
"""
import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ written in the skill directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check  # noqa: E402
import common  # noqa: E402
import disclaimer  # noqa: E402
import guards  # noqa: E402
import hybrid  # noqa: E402
import r3check  # noqa: E402
import v2check  # noqa: E402
import v3check  # noqa: E402
import v4check  # noqa: E402
import overlap  # noqa: E402
import matter
import tournament  # noqa: E402
import rebound  # noqa: E402

MAX_LINES = check.CARD_MAX_LINES
SAME_FAMILY = 'Critique: same family (no independent critic available)'
DEBATES_OFFER = 'Ranking of the neighbouring ideas by debates is available on request (tournament).'
BANNER_KEPT = 'REOPENS A TRIAL CLASSED BY YOUR PROJECT'
BANNER_NET = 'POSSIBLE OVERLAP WITH A TRIAL CLASSED BY YOUR PROJECT'
_FULL = False        # True while the complete IDEA-REPORT.md is rendered: nothing is clipped, no list is cut
_R3 = False          # True for a directory of round 3: the card never cuts a text and never says "(+k more"
_V2 = False          # True for a directory of Frontier v2: nothing is clipped at all, "Next step", marks, framing, plan
_LEVEL = 0           # R3 compaction level (0 = everything, 1 = per-test detail to the report, 2 = lists to the report)
_HEADS = {}          # v2: id of a test or idea -> the banner said at its head (a trial the project classed)
_MARKS = []          # v2: the marks of tools/check.py ("mark: [CODE] ...") of the directory being rendered
_DATA = {}           # v2: the files of the directory, as tools/check.py loads them
UNLIMITED = 10 ** 9
POINTER = ' [rest: %s]' % check.REPORT


class CardSizeError(ValueError):
    """The complete compacted candidate still exceeds the output-format cap."""

    def __init__(self, text, cap):
        self.text = text
        self.cap = cap
        self.line_count = len(text.splitlines())
        sections = {}
        section = 'Header / recommendation / actions'
        for line in text.splitlines():
            if line.startswith('## '):
                section = line[3:]
            elif line == 'Scenarios:' or line.startswith('- If '):
                section = 'Ranking scenarios'
            if line.strip():
                sections[section] = sections.get(section, 0) + 1
        super().__init__(
            '[CARD-SIZE] %s: %d lines exceed cap %d after all applicable compaction; '
            'could not move remaining content without removing conclusions, actions, leads, neighbours or scenarios. '
            'Retained sections (nonblank lines): %s. Full rendering is available with render(DIR, full=True); '
            'no output files were written.' % (
                check.CARD, self.line_count, cap,
                '; '.join('%s: %d' % item for item in sections.items())))


def bounded(text, cap):
    if len(text.splitlines()) > cap:
        raise CardSizeError(text, cap)
    return text


def top(seq, n):
    """The first n items of seq on the one-page card, all of them in the full report (and all of them on an R3 card)."""
    seq = list(seq)
    return seq if (_FULL or _R3) else seq[:n]


def clip(s, n):
    s = ' '.join(str(s or '').split())
    if _FULL or _V2 or len(s) <= n:                  # v2: a text is never shortened; the page falls back to the report by sections
        return s
    if _R3:                                # never mid-sentence: whole sentences that fit, else the first sentence whole
        parts = [p for p in check.SENTENCE_SPLIT.split(s) if p.strip()]
        keep, size = [], 0
        for p in parts:
            if keep and size + len(p) + 1 > n:
                break
            keep.append(p)
            size += len(p) + 1
        return ' '.join(keep) + (POINTER if len(keep) < len(parts) else '')
    return s[:n - 3].rstrip() + '...'


def whole(s, n):
    """A field that decides (conclusion, threshold, action, scenario): never clipped on an R3 card, clipped as before otherwise."""
    return ' '.join(str(s or '').split()) if _R3 else clip(s, n)


def bare(s, n):
    """clip() without a final period, for fields joined by ';' inside one line."""
    s = clip(s, n)
    return s if s.endswith('...') or s.endswith(']') else s.rstrip('.').rstrip()


def bare_whole(s, n):
    s = whole(s, n)
    return s if s.endswith('...') else s.rstrip('.').rstrip()


def load(work, name):
    p = work / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding='utf-8'))


class Refs:
    def __init__(self, work, intake):
        self.vp = check.VPRuns(work, intake) if check.get(intake, 'vp', 'mode') == 'vp' else None

    def fmt(self, ref):
        if not isinstance(ref, dict):
            return ''
        if self.vp is None:
            return '%s [unverified]' % ref.get('id')
        status, _, _ = check.ref_check(self.vp, ref)
        return '%s [%s]' % (ref.get('id'), status or 'no verdict')

    def many(self, refs, limit=3):
        refs = [r for r in (refs or []) if isinstance(r, dict)]
        if _FULL or _R3:
            limit = len(refs)
        out = ', '.join(self.fmt(r) for r in refs[:limit])
        if len(refs) > limit:
            out += ' (+%d)' % (len(refs) - limit)
        return out or 'none'


def pred_text(p):
    s = '%s: %s' % (p.get('hypothesis'), p.get('direction'))
    if isinstance(p.get('interval'), list):
        s += ' %s' % p['interval']
    if check.text(p.get('unit')):
        s += ' ' + clip(p['unit'], 40)
    return s


def sim_text(sens):
    sim = sens.get('simulation')
    if isinstance(sim, dict):
        what = ('distinguishes the scenarios' if sim.get('distinguishes')
                else 'does NOT distinguish the scenarios: the test is underpowered as planned')
        return 'simulation (tools/sim.py, %s, n=%s, seed %s, rerun by check.py): %s (lowest P(expected decision) = %s)' % (
            sim.get('design'), sim.get('n'), sim.get('seed'), what, sim.get('min_p_expected'))
    return 'simulation not applicable: %s' % clip(sens.get('simulation_not_applicable'), 110)


def trap_verdicts_text(cr, order):
    tv = cr.get('trap_verdicts') or {}
    parts = []
    for tid in order:
        per = tv.get(tid) or {}
        vs = [(per.get(t) or {}).get('verdict') for t in check.TRAPS]
        if all(v == 'not_returned' for v in vs):
            parts.append('%s not returned by this route' % tid)
            continue
        counts = {}
        for v in vs:
            counts[v] = counts.get(v, 0) + 1
        parts.append('%s %s' % (tid, ', '.join('%d %s' % (counts[k], k) for k in sorted(counts, key=str))))
    return 'Critic trap verdicts (4 traps per test): ' + '; '.join(parts)


NEIGHBOUR_NOTE = ('no novelty score, no model ranking; "Not found" is never a proof of absence or novelty; '
                  'Exists = already done: read, do not redo; recurring ingredients only (abstracts of 46 sources), '
                  'no efficacy figure')


def idea_line(it, refs, after, vp=True):
    op = '%s%s%s' % (it.get('operator'), ', not measured' if it.get('recurring_ingredient') is False else '',
                     ', %s' % it['follow_up_kind'] if after and it.get('follow_up_kind') else '')
    pa = it.get('prior_art') or {}
    status = pa.get('status')
    if pa.get('uncontrolled') is True:
        prior = 'prior art: not checked (budget used)'
    else:
        prior = 'prior art: %s' % status
        if status == 'Exists':
            prior += ' (already done: read, do not redo)'
        closest = [c for c in pa.get('closest_work') or [] if isinstance(c, dict)]
        if closest:
            c = closest[0]
            prior += ' (closest: %s, %s)' % (clip(c.get('title'), 45), refs.fmt(c.get('ref')))
        if pa.get('recognised_by_model_only') is True:
            prior += ' [unverified]'
        if not vp:
            prior += ' [not verified: no VP]'
    if rebound.original_scope(it):
        prior += '; prior art checked on the original statement'
    fe = it.get('feasibility') or {}
    ok = [k for k in ('data', 'tool', 'time', 'compute') if (fe.get(k) or {}).get('status') == 'established']
    no = [k for k in ('data', 'tool', 'time', 'compute') if k not in ok]
    feas = ('feasibility: %s established' % ', '.join(ok)) if not no else (
        'feasibility: not established: %s' % ', '.join(no) + ('; established: %s' % ', '.join(ok) if ok else ''))
    idea = it.get('statement') if (_V2 or 'original_statement' in it) else it.get('title')
    if _V2 and _FULL:
        idea = '%s: %s' % (it.get('title'), idea)
    shown = ' '.join(idea.split()) if 'original_statement' in it else clip(idea, 55)
    line = '- %s [%s] %s | %s | %s | test: %s' % (it.get('id'), op, shown, prior, feas,
                                                  clip((it.get('test') or {}).get('one_line'), 90))
    if _V2:
        if it.get('id') in _HEADS:                         # a trial the project classed: said first, before anything else
            line = '- %s %s: %s' % (it.get('id'), _HEADS[it['id']], line.split(' ', 2)[2])
        sp = it.get('search_plan') if isinstance(it.get('search_plan'), dict) else None
        if sp and _FULL:
            its = [i for i in sp.get('iterations') or [] if isinstance(i, dict)]
            line += '\n  search plan: %d iterations (%s); differs from the previous version: %s' % (
                len(its), '; '.join(', '.join(f.get('field') for f in i.get('fields') or [] if isinstance(f, dict)) for i in its),
                whole(sp.get('differs_from_previous'), 200))
    return line


def choice_line(d):
    sel = d.get('selection')
    if not isinstance(sel, dict):
        return 'No idea retained yet: the researcher chooses 0 to 2 after reading the checks.'
    rej = '; '.join('%s (%s)' % (r.get('id'), bare(r.get('reason'), 50)) for r in sel.get('rejected') or [])
    return 'Researcher choice (%s): retained: %s; rejected: %s' % (sel.get('decided_by'), ', '.join(sel.get('retained') or []) or 'none',
                                                                rej or 'none')


def block(d, refs, after, vp=True):
    ideas = [it for it in d.get('ideas') or [] if isinstance(it, dict)]
    if after and d.get('outcome_source') == 'scenario':
        head = ('## Scenarios, no result yet (if %s comes out %s): continuations to consider once a result exists; they are '
                'not a rebound after a result' % (d.get('after_test'), d.get('outcome')))
    elif after:
        head = '## Rebound after %s (%s, outcome from %s): next ideas conditioned on the outcome' % (
            d.get('after_test'), d.get('outcome'), d.get('outcome_source'))
    else:
        head = '## Neighbouring ideas (step 8): ' + NEIGHBOUR_NOTE
    extras = []
    groups = [g for g in d.get('duplicate_groups') or [] if isinstance(g, dict)]
    if groups:
        extras.append('Possible duplicates: %s (shown, not removed)' % '; '.join(
            '%s (%s)' % (', '.join(g.get('ids') or []), ', '.join(g.get('fields') or [])) for g in groups))
    if not after:
        head += ' | ' + rebound.summary(d)
    extras.append(choice_line(d))
    scen = []
    for s in top((d.get('ranking') or {}).get('scenarios') or [], 2):
        if isinstance(s, dict):
            scen.append('Scenario: if %s, then %s (%s)' % (bare_whole(s.get('if'), 70), bare_whole(s.get('then'), 40),
                                                          bare_whole(s.get('why'), 70)))
    return {'head': head, 'ideas': [idea_line(it, refs, after, vp) for it in ideas], 'extras': extras, 'scen': scen,
            'file': 'rebound_after.json' if after else 'rebound.json'}


def neighbour_lines(work, refs, avail):
    """Lines of the section(s) on neighbouring ideas, at most `avail`: scenarios go first, then ideas ("+k more in <file>")."""
    blocks = []
    vp = check.get(load(work, 'intake.json'), 'vp', 'mode') == 'vp'
    for name, after in (('rebound.json', False), ('rebound_after.json', True)):
        d = load(work, name)
        if isinstance(d, dict):
            blocks.append(block(d, refs, after, vp))
    if not blocks or avail <= 0:
        return []
    if _V2:
        # All neighbouring ideas and conditional continuations stay visible at every level.
        return [line for b in blocks for line in [b['head']] + b['ideas'] + b['extras'] + b['scen']]
    if _R3 and not _FULL and _LEVEL >= 2:        # legacy R3 lists go to the report
        out = []
        for b in blocks:
            out += [b['head'], '- %d idea(s): the list is in %s' % (len(b['ideas']), check.REPORT)] + b['extras']
        return out
    show = [len(b['ideas']) for b in blocks]
    use_scen = True

    def total():
        n = 0
        for b, k in zip(blocks, show):
            n += 1 + k + len(b['extras']) + (len(b['scen']) if use_scen else 0) + (1 if k < len(b['ideas']) else 0)
        return n
    if total() > avail:
        use_scen = False
    while total() > avail and any(k > 0 for k in show):
        i = max(range(len(show)), key=lambda x: show[x])
        show[i] -= 1
    out = []
    for b, k in zip(blocks, show):
        out.append(b['head'])
        out += b['ideas'][:k]
        if k < len(b['ideas']):
            out.append('- (+%d more in %s)' % (len(b['ideas']) - k, b['file']))
        out += b['extras']
        if use_scen:
            out += b['scen']
    return out[:avail]


def _opt(work, name):
    try:
        return load(work, name)
    except (ValueError, OSError):
        return None


def size_text(nts):
    if not isinstance(nts, dict):
        return 'needed n: not computed'
    if 'not_computable' in nts:
        return 'needed n: not computable (%s)' % clip(nts.get('not_computable'), 100)
    unit = 'pairs' if nts.get('design') == 'paired' else 'per arm'
    return 'needed n = %s %s (%s, effect %s, power %s, alpha %s%s)' % (
        nts.get('needed_n'), unit, nts.get('design'), nts.get('effect'), nts.get('power_target'), nts.get('alpha'),
        '' if nts.get('verified_by_simulation') else '; analytic only')


def effect_text(me):
    me = me if isinstance(me, dict) else {}
    if isinstance(me.get('value'), (int, float)):
        ci = ' CI %s' % me['ci'] if isinstance(me.get('ci'), list) else ''
        return '%s %s%s' % (me['value'], clip(me.get('unit'), 40), ci)
    return 'not reported (%s)' % clip(me.get('not_reported'), 80)


def power_origin(work):
    """Names of the context numbers the simulations of tests.json used, [] when none did."""
    tj = _opt(work, 'tests.json') or {}
    names = set()
    for t in tj.get('tests') or []:
        c = ((t.get('sensitivity') or {}).get('simulation') or {}).get('context') if isinstance(t, dict) else None
        if isinstance(c, dict) and c.get('used') is True:
            names.update(str((v or {}).get('name')) for v in (c.get('inputs') or {}).values())
    return sorted(names)


NEED = {'paired': ('n', 'sd'), 'means': ('n', 'sd'), 'proportions': ('n', 'base')}


def project_numbers_lines(work, intake):
    """v2: what became of every key number of the project in the power of each test, and what the project does not give."""
    ctx = (intake or {}).get('context')
    allk = [k for k in (ctx.get('key_numbers') if isinstance(ctx, dict) else None) or [] if isinstance(k, dict)]
    if not allk:
        return ['Project numbers and the power: no project numbers were given: every power input is an assumed range, not a measured value.']
    nums = v2check.usable_numbers(intake)
    tj = load(work, 'tests.json') or {}
    use_by, missing = {}, []
    for t in tj.get('tests') or []:
        sens = t.get('sensitivity') or {}
        sim = sens.get('simulation') if isinstance(sens.get('simulation'), dict) else None
        cb = (sim or {}).get('context') if isinstance((sim or {}).get('context'), dict) else {}
        inputs = cb.get('inputs') if cb.get('used') is True and isinstance(cb.get('inputs'), dict) else {}
        uses = {u.get('name'): u for u in (sens.get('power') or {}).get('context_use') or [] if isinstance(u, dict)}
        for k in nums:
            nm = k['name']
            role = next((r for r, i in inputs.items() if isinstance(i, dict) and i.get('name') == nm and sim.get(r) == k['value']), None)
            if role:
                txt = 'used by the simulation of %s as %s' % (t['id'], role)
            elif nm in uses:
                txt = 'not a simulation input for %s (%s)' % (t['id'], ' '.join(str(uses[nm].get('why')).split()))
            else:
                txt = 'neither used by the simulation of %s nor placed' % t['id']
            use_by.setdefault(nm, []).append(txt)
        if sim:
            miss = [p for p in NEED.get(sim.get('design'), ()) if p not in inputs]
            missing.append('%s: %s' % (t['id'], ', '.join(miss) or 'none'))
        else:
            missing.append('%s: no simulation (%s)' % (t['id'], ' '.join(str(sens.get('simulation_not_applicable') or 'not applicable').split())))
    gap = 'missing from the project numbers (assumed range or chosen by hand): %s' % '; '.join(missing)
    if not _FULL:
        return ['Project numbers and the power: %s; %s.' % ('; '.join('%s = %s %s' % (
            k['name'], k['value'], 'used' if any(x.startswith('used') for x in use_by.get(k['name'], [])) else 'not a simulation input')
            for k in nums), gap)]
    L = ['', '## Project numbers and the power (intake.json context)', 'Project numbers and the power: %d key number(s) given.' % len(allk)]
    for k in allk:
        if k in nums:
            L.append('- %s = %s%s (%s%s): %s' % (k['name'], k['value'], ' ' + k['unit'] if k.get('unit') else '', k.get('source'),
                                                  ', read at %s' % k['cited'] if k.get('cited') else '', '; '.join(use_by.get(k['name'], []))))
        else:
            L.append('- %s = %s (%s, not confirmed): not used' % (k.get('name'), k.get('value'), k.get('source')))
    L.append('- ' + gap)
    return L


def extras(work, intake, refs):
    """Lines of the sections added in the AM1 round, each only when its file exists: the card gets one line (or none), the
    report the whole section. {draft, context, matter, moment, evidence} -> list of lines."""
    out = {'draft': [], 'context': [], 'matter': [], 'moment': [], 'evidence': []}
    counts = check.draft_counts(work)
    if counts is not None:
        n = sum(counts.values())
        summary = 'Free draft (free_draft.md): %d claims: %d verified (VP), %d unverified (memory), %d removed; every item of ' \
                  'the draft taken up in this card is verified or carries the mark "unverified (memory)".' % (
                      n, counts['verified'], counts['unverified_memory'], counts['removed'])
        if not _FULL:
            out['draft'] = [summary] + ([hybrid.richness_line(hybrid.richness(work))] if _R3 else [])
        else:
            out['draft'] = ['', '## Free draft (free_draft.md): status of every claim', summary]
            if _R3:
                out['draft'].append(hybrid.richness_line(hybrid.richness(work)))
            for c in (_opt(work, 'draft_claims.json') or {}).get('claims') or []:
                if c.get('status') == 'verified':
                    st = 'verified: %s' % refs.fmt(c.get('ref'))
                elif c.get('status') == 'unverified_memory':
                    st = 'unverified (memory)'
                else:
                    st = 'removed%s' % (': ' + clip(c.get('why'), 200) if c.get('why') else '')
                out['draft'].append('- %s [%s] %s' % (c.get('id'), st, clip(c.get('quote'), 300)))
        if _V2:
            rows = hybrid.submissions(work)
            by_id = {r['id']: r for r in rows}
            out['draft'].append('Free verification: %d submitted to VP; %d verdicts; claims and verdicts: %s.' % (
                sum(r['submitted'] for r in rows), sum(r['verdict'] is not None for r in rows), check.REPORT))
            if not _FULL:
                # Successful verification is not required to keep a lead. Never hide an unselected idea.
                for c in hybrid._claims(work):
                    r = by_id.get(c.get('id'), {})
                    if not r.get('submitted'):
                        out['draft'].append('- Draft %s [unverified (memory)] %s' % (c.get('id'), whole(c.get('quote'), 300)))
                    elif r.get('verdict') != 'FOUND':
                        # submitted but not supported (no verdict yet, ABSENT, ...): still an open lead
                        out['draft'].append('- Draft %s [submitted, VP: %s] %s' % (
                            c.get('id'), r.get('verdict') or 'no verdict yet', whole(c.get('quote'), 300)))
            else:
                for c in hybrid._claims(work):
                    r = by_id.get(c.get('id'), {})
                    out['draft'].append('- VP verdict for %s: %s; %s%s' % (
                        c.get('id'), r.get('verdict') or 'unverified (memory)', whole(c.get('quote'), 300),
                        ' (full verdict: %s)' % r['where'] if r.get('where') and r.get('verdict') else ''))
    ctx = (intake or {}).get('context')
    if _V2:
        out['context'] = project_numbers_lines(work, intake)
    elif isinstance(ctx, dict):
        kns = [k for k in ctx.get('key_numbers') or [] if isinstance(k, dict)]
        used = power_origin(work)
        origin = ('power inputs: from the project context (%s)' % ', '.join(used)) if used else \
            "power inputs: not tied to the project's numbers (the simulations use values chosen by hand)"
        if not _FULL:
            out['context'] = ['Context: %d key numbers; %s.' % (len(kns), origin)]
        else:
            L = ['', '## Context (intake.json context)']
            if ctx.get('objective'):
                L.append('Objective: %s' % clip(ctx['objective'], 400))
            if ctx.get('data_available'):
                L.append('Data available: %s' % '; '.join(clip(x, 200) for x in ctx['data_available']))
            if ctx.get('constraints'):
                L.append('Constraints: %s' % '; '.join(clip(x, 200) for x in ctx['constraints']))
            for k in kns:
                L.append('- %s = %s%s (%s%s%s)' % (k.get('name'), k.get('value'), ' ' + k['unit'] if k.get('unit') else '',
                                                    k.get('source'), ', confirmed' if k.get('confirmed') else '',
                                                    ', read at %s' % k['cited'] if k.get('cited') else ''))
            L.append('Power: %s.' % origin)
            out['context'] = L
    ev = _opt(work, 'evidence_table.json')
    if isinstance(ev, dict):
        entries = [e for e in ev.get('entries') or [] if isinstance(e, dict)]
        if not _FULL:
            parts = ['%s (%s) %s, replicated: %s, %s' % (e.get('id'), e.get('lead'), effect_text(e.get('measured_effect')),
                                                         e.get('replication'), size_text(e.get('needed_test_size')))
                     for e in (entries if _R3 else entries[:2])]
            more = ' (+%d more in evidence_table.json)' % (len(entries) - 2) if len(entries) > 2 and not _R3 else ''
            out['evidence'] = ['Expected effects: ' + '; '.join(parts) + more] if parts else \
                ['Expected effects: no measured effect found for any lead (evidence_table.json)']
        else:
            L = ['', '## Expected effects already measured (evidence_table.json)']
            for e in entries:
                src = e.get('source')
                L.append('- %s (%s): source %s; sample: %s; effect: %s; replicated: %s%s; %s' % (
                    e.get('id'), e.get('lead'), refs.fmt(src) if isinstance(src, dict) else 'none',
                    clip(e.get('sample'), 300), effect_text(e.get('measured_effect')), e.get('replication'),
                    ' (%s)' % clip(e['replication_note'], 200) if e.get('replication_note') else '',
                    size_text(e.get('needed_test_size'))))
            for n_ in ev.get('no_evidence') or []:
                L.append('- %s: no measured effect found; searched: %s (never a proof of absence)' % (n_.get('lead'), clip(n_.get('searched'), 300)))
            out['evidence'] = L
    mat = matter.normalize_material(_opt(work, 'material.json'))
    if isinstance(mat, dict):
        out['matter'] = matter_lines(work, mat)
    mo = _opt(work, 'moment.json')
    if isinstance(mo, dict):
        line = mo.get('line')
        if _R3 and 'unverified provenance' not in str(line):       # recomputed now: an edited moment.json cannot hide it
            if any(guards.provenance(work, s.get('envelope'))[0] != 'journal-attested' for s in mo.get('series') or []
                   if isinstance(s, dict)):
                line = '%s (unverified provenance: the gateway journal does not bind these totals)' % line
        if not _FULL:
            out['moment'] = [clip(line, 300)]
        else:
            L = ['', '## Moment of the subject', clip(line, 600),
                 'Query: %s (engine %s). Totals are publications dated before each date, the gateway\'s index total; '
                 'they describe the index, not the truth.' % (mo.get('query'), mo.get('engine'))]
            for s in mo.get('series') or []:
                L.append('- %s: index total %s (%s)' % (s.get('as_of'), s.get('total'), s.get('envelope')))
            for p in mo.get('periods') or []:
                L.append('- %s to %s: %s new, %s per year' % (p.get('from'), p.get('to'), p.get('count'), p.get('per_year')))
            L.append('Reading thresholds (config.json moment): %s' % json.dumps(mo.get('thresholds'), sort_keys=True))
            if mo.get('directions_note'):
                L.append('Directions index: %s' % clip(mo['directions_note'], 300))
            out['moment'] = L
    return out


def matter_lines(work, mat):
    items = [i for i in mat.get('items') or [] if isinstance(i, dict)]
    opt = mat.get('optional_sources') if isinstance(mat.get('optional_sources'), dict) else {}

    def opt_text(key, label):
        o = opt.get(key) if isinstance(opt.get(key), dict) else {}
        if o.get('status') == 'used':
            ms = ['%s' % (m.get('id') or m.get('direction')) for m in o.get('matches') or [] if isinstance(m, dict)]
            return '%s: used (%d match(es): %s)' % (label, len(ms), clip(', '.join(ms), 160) or 'none')
        return '%s: skipped (%s)' % (label, clip(o.get('reason'), 160))
    if not _FULL:
        main = [i for i in items if i.get('for') == 'main']
        counts = {k: sum(1 for i in main if i.get('kind') == k) for k in ('code', 'dataset', 'benchmark')}
        best = next((i for i in main if i.get('kind') == 'code'), None)
        bestt = ' (%s, %s, last activity %s)' % (best.get('name'), best.get('licence'), best.get('last_activity') or 'unknown') if best else ''
        ideas = set()
        for fname in ('rebound.json', 'rebound_after.json'):
            d = _opt(work, fname)
            ideas.update(i.get('id') for i in (d.get('ideas') if isinstance(d, dict) else None) or [] if isinstance(i, dict))
        covered = {i.get('for') for i in items} | {s.get('for') for s in mat.get('searched') or [] if isinstance(s, dict) and s.get('result') == 'not found'}
        cov = '; neighbouring ideas covered: %d of %d' % (len(ideas & covered), len(ideas)) if ideas else ''
        unv = ''
        if _R3:
            n_unv = sum(1 for i in items if i.get('via') == 'gateway' and guards.provenance(work, i.get('envelope'))[0] != 'journal-attested')
            unv = '; %d item(s) with unverified provenance (the gateway journal does not bind them)' % n_unv if n_unv else ''
        return ['Matter (existing code, data, benchmarks found through VP\'s gateway): main: %d code%s, %d dataset, %d benchmark%s%s; '
                '%s; %s.' % (counts['code'], bestt, counts['dataset'], counts['benchmark'], cov, unv,
                             opt_text('catalogue', 'catalogue'), opt_text('directions', 'directions index'))]
    prov = {}
    if _R3:
        prov = {i.get('envelope'): guards.provenance(work, i.get('envelope'))[0] for i in items if i.get('via') == 'gateway'}
    if _R3 and any(v != 'journal-attested' for v in prov.values()):
        L = ['', '## Matter: existing code, datasets and benchmarks (searched through VP\'s gateway; per line, only a value that '
             'the gateway journal binds is shown as extracted)']
    else:
        L = ['', '## Matter: existing code, datasets and benchmarks (found through VP\'s gateway; licence and last activity are read '
             'from the saved gateway answer)']
    for i in items:
        flag = 'via gateway (%s)' % i.get('envelope') if i.get('via') == 'gateway' else \
            "not verified (host's own search, not VP's gateway)"
        if i.get('via') == 'gateway' and prov.get(i.get('envelope'), 'journal-attested') != 'journal-attested':
            flag = 'unverified provenance (envelope %s kept; the gateway journal does not bind its content)' % i.get('envelope')
        L.append('- %s %s: %s | licence %s | last activity %s (%s) | %s%s' % (
            i.get('for'), i.get('kind'), i.get('name'), i.get('licence'), i.get('last_activity') or 'unknown',
            i.get('last_activity_basis', 'unknown'), flag, ' | ' + clip(i['note'], 200) if i.get('note') else ''))
    for s in mat.get('searched') or []:
        if isinstance(s, dict) and s.get('result') == 'not found':
            L.append('- %s %s: not found; searched: %s. "Not found" is never a proof of absence.' % (
                s.get('for'), s.get('kind'), '; '.join(clip(q, 200) for q in s.get('queries') or [])))
    L.append('Optional sources (never required):')
    L.append('- ' + opt_text('catalogue', 'catalogue'))
    L.append('- ' + opt_text('directions', 'directions index'))
    return L


def history_block(work, intake):
    """(status for the head of the card, lines of the section "Already tried here"). Not checked: no project folder given."""
    dirs = check.project_dirs(intake)
    if not dirs:
        return 'not checked (no project_dirs given)', []
    hist = load(work, check.HISTORY) or {}
    ents = [e for e in hist.get('entries') or [] if isinstance(e, dict)]
    by_id = {e.get('id'): e for e in ents}
    scan = hist.get('scan') or {}
    classed = [e for e in ents if e.get('verdict') == 'classed']
    tried = [e for e in ents if e.get('verdict') == 'tried']
    data = {name: load(work, name) for name in ['tests.json'] + list(check.REBOUND_FILES)}
    kept, removed = {}, []
    for fname, iid, obj, _ in check.history_items(data):
        for it in obj.get('internal_history') or []:
            e = by_id.get(it.get('entry'))
            if e is not None:
                slot = kept.setdefault((e.get('root'), e.get('file')), {'items': [], 'entry': e, 'cond': it.get('reopen_condition')})
                if iid not in slot['items']:
                    slot['items'].append(iid)
    for fname, d in data.items():
        for n in (d.get('internal_history_removed') if isinstance(d, dict) else None) or []:
            removed.append('- removed: %s (%s): %s' % (clip(n.get('what'), 60), n.get('cited'), clip(n.get('why'), 80)))
    L = ['## Already tried here (internal history)',
         'Searched %d file(s) in %d folder(s)%s; %d passage(s) found: %d classed, %d tried. A search that finds nothing is not a '
         'proof that nothing was tried.' % (scan.get('files_scanned', 0), len(dirs),
                                            ' (stopped at the limits)' if scan.get('truncated') else '', len(ents),
                                            len(classed), len(tried))]
    files = {}
    for e in classed:
        files.setdefault((e.get('root'), e.get('file')), []).append(e)
    rows = []
    for key in sorted(files, key=lambda k: str(k)):
        slot = kept.get(key)
        e = slot['entry'] if slot else files[key][0]
        cond = (slot['cond'] if slot else e.get('reopen_condition')) or None
        use = 'kept by %s' % ', '.join(slot['items']) if slot else 'no test or idea overlaps it'
        rows.append('- %s:%s [%s] reopen: %s | %s' % (e.get('file'), e.get('line'), ', '.join((e.get('markers') or [])[:3]),
                                                    clip(cond, 90) if cond else 'no written reopening condition', use))
    L += top(rows, 5)
    if len(rows) > 5 and not (_FULL or _R3):
        L.append('- (+%d more classed files in history.json)' % (len(rows) - 5))
    if tried:
        L.append('- tried, no closing verdict: %s%s' % (', '.join('%s:%s' % (e.get('file'), e.get('line')) for e in top(tried, 3)),
                                                       ' (+%d)' % (len(tried) - 3) if len(tried) > 3 and not (_FULL or _R3) else ''))
    L += top(removed, 3)
    if len(removed) > 3 and not (_FULL or _R3):
        L.append('- (+%d more removals in the JSON files)' % (len(removed) - 3))
    gen = [t for q in hist.get('queries') or [] for t in q.get('terms') or [] if isinstance(t, dict) and t.get('generic')]
    if gen:
        L.append('- generic terms (not used to find an overlap): %s' % clip(', '.join(sorted({t['term'] for t in gen})), 120))
    return 'checked (%d folder(s), %d file(s) read)' % (len(dirs), scan.get('files_scanned', 0)), L


def _r3_test_lines(L, t):
    """Per test on the R3 card: the grid in short form, then what decides whole (rule, scope, power inputs, feasibility)."""
    di, rule, sens, feas = t['decisive_intervention'], t['decision_rule'], t['sensitivity'], t['feasibility']
    L.append('- Competing: %s. Predictions: %s. Compatible with both: %s. Unexpected under both: %s' % (
        ' vs '.join(t['competing_hypotheses']), '; '.join(pred_text(p) for p in t['predictions']),
        bare_whole(t['compatible_with_both'], 70), bare_whole(t['unexpected_under_both'], 70)))
    if _LEVEL < 1:
        L.append('- Decisive intervention (%s): %s' % (', '.join(di['kind']), whole(di['description'], 160)))
    eq = rule['equivalence']
    L.append('- Decision rule, fixed before observation: continue if %s; revise if %s; stop if %s; indeterminate if %s. '
             'Equivalence: %s.' % (bare_whole(rule['continue_if'], 90), bare_whole(rule['revise_if'], 80),
                                   bare_whole(rule['stop_if'], 80), bare_whole(rule['indeterminate_if'], 60),
                                   'margin ' + whole(eq.get('margin'), 50) if eq.get('relevant')
                                   else 'not relevant (%s)' % bare_whole(eq.get('why_not'), 50)))
    L.append('- ' + scope_text(t))
    ptxt = power_text(t)
    L.append('- Sensitivity: smallest useful effect %s; noise %s; replications %s; %s%s' % (
        bare_whole(sens['smallest_useful_effect'], 60), bare_whole(sens['expected_noise'], 60), bare_whole(sens['replications'], 40),
        sim_text(sens), '' if ptxt is None else '. ' + ptxt))
    if _LEVEL < 1:
        L.append('- Feasibility: data %s; human time %s; compute %s; risk %s' % (
            whole(feas['data'], 70), bare_whole(feas['human_time'], 40), bare_whole(feas['compute'], 40), whole(feas['technical_risk'], 70)))
        traps = t['traps']
        pv, va, pc, ds = traps['proxy_vs_target'], traps['variants'], traps['positive_control'], traps['data_split']
        L.append('- Traps: proxy %s vs target %s; %d variant(s) tested; positive control: %s; design data (%s) apart from confirmation '
                 'data (%s)' % (bare_whole(pv['proxy'], 40), bare_whole(pv['target'], 40), va['number_tested'],
                                bare_whole(pc['description'], 70), bare_whole(ds['design_data'], 40), bare_whole(ds['confirmation_data'], 40)))


def v2_test_lines(t):
    """v2, per test and on every card level: the value of information over cost, and what each outcome does to the belief."""
    L = []
    v = t.get('voi') or {}
    L.append('- Information vs cost: information %s / cost %s: %s' % (v.get('information'), v.get('cost'), whole(v.get('why'), 160)))
    bs = t.get('belief_shift') or {}
    comp = t.get('competing_hypotheses') or []
    parts = []
    for o in bs.get('outcomes') or []:
        mv = o.get('moves') or {}
        parts.append('if %s: %s%s' % (o.get('matches') if o.get('matches') in ('ambiguous', 'unexpected') else '%s matches' % o.get('matches'),
                                      ', '.join('%s %s' % (h, mv.get(h)) for h in comp),
                                      ', then %s' % bare_whole(o.get('then'), 100) if o.get('then') else ''))
    L.append('- Belief after %s (%s; scenarios, no probability): %s' % (
        t.get('id'), 'the explanations exclude each other' if bs.get('exclusive') else 'the explanations may hold together', '; '.join(parts)))
    return L


def next_step_lines(tj, reco):
    """The "Next step" block of a v2 card: first gesture, inputs, cost, stop rule, the last three copied whole from the first test."""
    ns = reco.get('next_step') or {}
    t = next((x for x in tj['tests'] if x.get('id') == ns.get('test')), tj['tests'][0])
    f = t['feasibility']
    return ['## Next step',
            'First step: %s (%s)' % (whole(ns.get('first_action'), 200), t['id']),
            'Inputs: %s' % whole(f['data'], 200),
            'Cost: %s; compute: %s' % (bare_whole(f['human_time'], 80), bare_whole(f['compute'], 80)),
            'Stop rule: %s' % whole(t['decision_rule']['stop_if'], 200)]


def framing_lines(work):
    f = load(work, 'framing.json') or {}
    ap, final = f.get('approval') or {}, f.get('final') or f.get('proposal') or {}
    st = ap.get('status')
    if st == 'approved':
        head = 'Framing: approved by the user'
    elif st == 'corrected':
        head = 'Framing: corrected by the user (%s)' % ', '.join(ap.get('changes') or [])
    else:
        reason = str(ap.get('reply') or '')
        reason = reason[len('ASSUMED:'):] if reason.startswith('ASSUMED:') else reason
        head = 'Framing: ASSUMED (%s)' % reason.strip().rstrip('.')
    arch = (f.get('archives') or {}).get('note')
    return ['## Framing', head,
            'Objective: %s' % whole(final.get('objective'), 200),
            'Success criterion: %s' % whole(final.get('success_criterion'), 200),
            'Constraints: %s' % '; '.join(whole(c, 100) for c in final.get('constraints') or []),
            'Would be refuted by: %s' % '; '.join(whole(c, 100) for c in final.get('refuted_by') or []),
            'Project archives: %s' % arch]


def tomorrow_lines(tj, reco):
    """The five lines of "Tomorrow" (round 3, 2.2). Only the first gesture is written by the host; the other lines are the
    feasibility and the stop rule of the first test, copied whole."""
    tid = (reco.get('tomorrow') or {}).get('test')
    t = next((x for x in tj['tests'] if x.get('id') == tid), tj['tests'][0])
    f = t['feasibility']
    return ['## Tomorrow',
            'First step: %s (%s)' % (whole((reco.get('tomorrow') or {}).get('first_action'), 200), t['id']),
            'Inputs: %s' % whole(f['data'], 200),
            'Cost: %s; compute: %s' % (bare_whole(f['human_time'], 80), bare_whole(f['compute'], 80)),
            'Stop rule: %s' % whole(t['decision_rule']['stop_if'], 200)]


def scope_text(t):
    sc = t.get('verdict_scope') if isinstance(t.get('verdict_scope'), dict) else {}
    seen = ((t.get('traps') or {}).get('data_split') or {}).get('data_seen_before')
    return 'Scope: concludes only about %s; does not conclude about %s%s' % (
        bare_whole(sc.get('concludes_about'), 120), '; '.join(bare_whole(x, 80) for x in sc.get('does_not_conclude_about') or []),
        '; data already seen: %s' % bare_whole(seen, 80) if seen else '')


def power_text(t):
    pw = (t.get('sensitivity') or {}).get('power')
    if not isinstance(pw, dict):
        return None
    ps = []
    for p in pw.get('parameters') or []:
        if isinstance(p, dict):
            if p.get('status') == 'assumed':
                ps.append('%s assumed (%s / %s / %s)' % (p.get('name'), p.get('low'), p.get('central'), p.get('high')))
            else:
                src = p.get('source') or {}
                ps.append('%s measured = %s (%s)' % (p.get('name'), p.get('value'), src.get('name') or (src.get('ref') or {}).get('id') or src.get('kind')))
    rb = pw.get('robust')
    s = 'Power inputs, protocol-support simulation (not an experiment): target %s; %s' % (bare_whole(pw.get('target_metric'), 80), '; '.join(ps))
    if isinstance(rb, dict):
        s += ('; over sd %s, rho %s, overlap %s: false positives under the null at most %s, power under the useful effect at least %s, '
              'effective n at least %.0f of %s' % (rb.get('sd_values'), rb.get('rho_values'), rb.get('overlap'),
                                                    '%.3f' % rb.get('false_positive_max'), '%.3f' % rb.get('power_min'),
                                                    rb.get('effective_n_min'), rb.get('n')))
    if isinstance(rb, dict) and (rb.get('power_min', 1) < 0.8 or rb.get('false_positive_max', 0) > 0.10):
        s += '; UNDERPOWERED or too many false positives under the perturbed assumptions (targets: power 0.8, false positives 0.10)'
    if pw.get('metric_is_target') is False:
        s += '; proxy gap: %s' % bare_whole(pw.get('proxy_gap'), 100)
    return s


def operator_note(item):
    """v2: ", operator X (recurring ingredient | operator not measured), facet F" for a rival or a variant made by a named operator."""
    if not _V2 or not item.get('operator'):
        return ''
    return ', operator %s, facet %s' % (v2check.operator_label(item['operator']), item.get('facet'))


def named_lines(work):
    """v2: every named dataset, model, metric: its existence, as it was checked. Nothing is dropped, only marked."""
    nj = load(work, 'named_elements.json') or {}
    out = []
    for e in nj.get('elements') or []:
        ev, ex = e.get('evidence') or {}, e.get('existence')
        if ex == 'verified':
            how = ('verified: item %s found through the gateway' % ev.get('item')) if ev.get('kind') == 'material' else \
                ('verified: %s, claim %s, FOUND by VP' % ((ev.get('ref') or {}).get('id'), (ev.get('ref') or {}).get('claim')))
        elif ex == 'host_checked':
            how = 'checked by the host, not by VP: %s' % whole(ev.get('how'), 160)
        elif ex == 'not_found':
            how = 'NOT FOUND (searched: %s): do not rely on it' % '; '.join(ev.get('queries') or [])
        else:
            how = 'unverified (memory): %s' % whole(ev.get('why'), 160)
        out.append('- Named %s %s %s [%s] used in %s' % (e.get('id'), e.get('kind'), e.get('name'), how, ', '.join(e.get('used_in') or [])))
    return out


def plan_lines(work, refs, vp):
    """v2: the iterative research plan, its outcome backed by a passage, its coverage (observable, never a recall)."""
    plan = load(work, 'research_plan.json') or {}
    its = [i for i in plan.get('iterations') or [] if isinstance(i, dict)]
    out = plan.get('outcome') or {}
    fields = []
    for it in its:
        for f in it.get('fields') or []:
            if isinstance(f, dict) and f.get('field') not in fields:
                fields.append(f.get('field'))
    L = ['- Research plan: %d iterations, %d fields questioned (%s); outcome: %s%s' % (
        len(its), len(fields), ', '.join(str(f) for f in fields), out.get('status'), '' if vp else ' [not verified: no VP]')]
    ps = out.get('passage') if isinstance(out.get('passage'), dict) else None
    if ps:
        L.append('- Passage backing the outcome: "%s" (%s)%s' % (whole(ps.get('fragment'), 120), refs.fmt(ps.get('ref')),
                                                             '; difference: %s' % whole(out.get('difference'), 160) if out.get('difference') else ''))
    elif out.get('summary'):
        L.append('- Outcome: %s' % whole(out.get('summary'), 200))
    if isinstance(plan.get('coverage'), dict) and (_FULL or not _V2):
        L.append('- Research ' + guards.coverage_line(plan['coverage'])[0].lower() + guards.coverage_line(plan['coverage'])[1:])
        if out.get('status') in ('Not found', 'Insufficient search'):
            L.append('- ' + guards.not_found_note(plan['coverage']) + '.')
    ss = plan.get('scope_split')
    if isinstance(ss, dict):
        L.append('- Scope: against the whole field: %s; against the works the idea cites itself: %s (two different answers)' % (
            ss.get('whole_field'), ss.get('cited_by_idea')))
    if _FULL or (not _V2 and _LEVEL < 1):
        for it in its:
            rev = it.get('revision') if isinstance(it.get('revision'), dict) else {}
            L.append('- Iteration %s: %s; %d search(es) through the gateway; %d work(s) found; %s' % (
                it.get('n'), '; '.join('%s (%s)' % (f.get('field'), ', '.join(f.get('keywords') or [])) for f in it.get('fields') or [] if isinstance(f, dict)),
                len(it.get('calls') or []), len(it.get('found') or []),
                'revision: %s' % whole(rev.get('learned'), 160) if rev else 'stopped: %s' % whole(it.get('stop_reason'), 160)))
    if _V2 and not _FULL:
        L.append('- Research detail and coverage: %s; recall unknown.' % check.REPORT)
    return L


def decisive_lines(work, refs, intake):
    cj = _opt(work, 'decisive_claims.json')
    out, supporting = [], []
    for c in (cj.get('claims') if isinstance(cj, dict) else None) or []:
        if isinstance(c, dict):
            if _V2 and not _FULL and _LEVEL >= 3 and c.get('decides') != 'verdict':
                supporting.append(str(c.get('id')))
                continue
            st = refs.fmt(c.get('ref')) if isinstance(c.get('ref'), dict) else 'no reference'
            note = '' if c.get('supports') == 'full' and '[FOUND]' in st else ' (not fully verified: %s)' % (
                'supports ' + str(c.get('supports')) if c.get('supports') != 'full' else st)
            line = '- Decisive evidence %s (%s): %s %s, supports %s%s' % (
                c.get('id'), c.get('decides'), whole(c.get('claim'), 100), st, c.get('supports'), note)
            if _V2 and not _FULL:
                out.append(line + '; scope and limits: ' + check.REPORT)
                continue
            out.append('- Decisive evidence %s (%s): %s %s, supports %s%s; scope: %s; limits: %s' % (
                c.get('id'), c.get('decides'), whole(c.get('claim'), 100), st, c.get('supports'), note,
                bare_whole(c.get('scope'), 80), bare_whole(c.get('limits'), 80)))
    if supporting:
        out.append('- Decisive evidence %s: supporting claims, references, scope and limits in %s.' %
                   (', '.join(supporting), check.REPORT))
    return out


def coverage_lines(pa):
    cov = pa.get('coverage')
    if not isinstance(cov, dict):
        return []
    out = ['- Coverage detail: %s; recall unknown.' % check.REPORT] if _V2 and not _FULL else ['- ' + guards.coverage_line(cov)]
    if pa.get('answer') == 'Not found':
        out.append('- ' + guards.not_found_note(cov) + '.')
    return out


def render(work, full=False):
    """The text of IDEA-CARD.md (one page), or of IDEA-REPORT.md when full is true (the same files, nothing clipped).
    A directory of round 3 gets the complete card: no text cut, no "(+k more", a "Tomorrow" block; when the whole does not
    fit on one page, the per-test detail and then the lists go to the report, never a cut sentence."""
    global _FULL, _R3, _V2, _LEVEL
    old = _FULL, _R3, _V2, _LEVEL
    _FULL, _R3, _V2 = bool(full), guards.is_r3(work), guards.is_v2(work)
    try:
        if _V2:
            v2_setup(Path(work))
        if full:
            _LEVEL = 0
            return _render(Path(work), bool(full))
        cap = common.config().get('card_max_lines', 80) if _V2 else MAX_LINES
        if not _R3:
            _LEVEL = 0
            return bounded(_render(Path(work), False), cap)
        text = ''
        for level in ((0, 1, 2, 3, 4) if _V2 else (0, 1, 2)):
            _LEVEL = level
            text = _render(Path(work), False)
            if _V2 and level >= 2:
                text = compact_v2(text)
            if _V2 and level >= 4:
                # Two supporting headings need no separate line on a dense
                # page. Keep their complete prose, plus the standalone V4
                # summaries and every lead. The report retains the headings.
                lines = text.splitlines()
                out = []
                for index, line in enumerate(lines):
                    if line == '## Framing':
                        continue  # the next line already begins "Framing:"
                    if line == '## Idea':
                        continue
                    if index and lines[index - 1] == '## Idea':
                        line = 'Idea: ' + line
                    out.append(line)
                if len(out) > cap and DEBATES_OFFER in out:
                    # On a full page the offer needs its own line. Inline the
                    # supporting Result heading, keeping its complete text.
                    for index, line in enumerate(out[:-1]):
                        if line == '## Result':
                            out[index + 1] = 'Result: ' + out[index + 1]
                            del out[index]
                            break
                text = '\n'.join(out) + '\n'
            if len(text.splitlines()) <= cap:
                break
        return bounded(text, cap)
    finally:
        _FULL, _R3, _V2, _LEVEL = old


def compact_v2(text):
    """Pack adjacent supporting fields, keeping every sentence and decision.

    Idea/scenario lines and the five-line Next step block always stand alone.
    The complete report preserves the spacious layout and all research detail.
    """
    import re
    out, pending = [], []
    protected = re.compile(r'^(?:#|\*\*Recommendation|First step:|Inputs:|Cost:|Stop rule:|'
                           r'Free draft|Free phase|Free verification|Scenario:|- If |'
                           r'Pitfalls present:|Prospective |'
                           r'Test revision:|Overlap ledger:|Tournament \[TOURNAMENT\]:|Ranking of the neighbouring ideas by debates |'
                           r'- (?:N\d+|B\d+|Draft |Decisive evidence|Closest tool/platform:)|<!--)')
    def flush():
        if pending:
            out.append(' | '.join(pending))
            pending.clear()
    for line in text.splitlines():
        if not line.strip():
            flush()
        elif protected.match(line) or line in disclaimer.DISCLAIMER.values():
            flush()
            out.append(line)
        else:
            pending.append(line)
    flush()
    return '\n'.join(out) + '\n'


def v2_setup(work):
    """Read once what a v2 card needs besides its own JSON files: the marks of tools/check.py and the trials of the project's own
    archives that a test or an idea reopens or may overlap (the banner said at its head)."""
    global _HEADS, _MARKS, _DATA
    data, _ = check.load(work)
    _DATA = data
    _, W = check.run_all(work, with_card=False)
    _MARKS = [w[len('mark: '):] for w in W if w.startswith('mark: ')]
    _HEADS = {}
    for fname, iid, obj, _skip in check.history_items(data):
        items = [i for i in obj.get('internal_history') or [] if isinstance(i, dict)]
        if items:
            _HEADS[iid] = '%s (%s)' % (BANNER_KEPT, '; '.join(
                '%s [%s], written reopening condition "%s", met now: %s' % (
                    i.get('cited'), i.get('verdict_quoted'), i.get('reopen_condition'), i.get('condition_met')) for i in items))
    for h in v2check.history_net(work, data, [], check):
        e = h['entry']
        _HEADS.setdefault(h['id'], '%s (%s:%s [%s]; shares %s)' % (BANNER_NET, e.get('file'), e.get('line'),
                                                                 ', '.join(e.get('markers') or []), ', '.join(h['shared'])))


def _render(work, full):
    intake = load(work, 'intake.json')
    pa = load(work, 'prior_art.json')
    hy = load(work, 'hypotheses.json')
    tj = load(work, 'tests.json')
    cr = load(work, 'critique.json')
    res = load(work, 'result.json')
    reco = load(work, 'recommendation.json')
    refs = Refs(work, intake)
    vp = check.get(intake, 'vp', 'mode') == 'vp'
    L = [disclaimer.get_disclaimer(intake.get('language'))]
    if not vp:
        L += [check.HEADER, '']
    else:
        unv = check.unverified_references(work)
        if unv:
            L += ['Unverified references: %s' % clip(', '.join('%s [%s]' % u for u in unv), 400), '']
    L.append('# Idea %s: %s' % ('report' if full else 'card', clip(check.sentences(intake['idea'])[0], 90)))
    L.append('')
    hist_status, hist_lines = history_block(work, intake)
    L.append('T %s | domain: %s | language: %s | %s | Already tried here: %s | assembled by tools/card.py from the JSON '
             'files of this directory; this card is not a certification of novelty or value.' % (
                 intake['T'], clip(intake['domain'], 40), intake.get('language', '?'), Path(work).resolve().name, hist_status))  # resolved: same name for '.' and an absolute path
    L.append('')
    L.append('**Recommendation: %s**: %s%s' % (reco['verdict'].upper(), whole(reco['reason'], 300),
                                             v3check.recommendation_note(tj, reco)))
    L.append('')
    if _V2:
        L += next_step_lines(tj, reco) + [''] + framing_lines(work) + ['']
    elif _R3:
        L += tomorrow_lines(tj, reco) + ['']
    if not _FULL and tournament.present(work):
        L.append(tournament.summary(work))
    L.append('## Idea')
    L.append(clip(intake['idea'], 400))
    gain = intake['justifying_gain']
    L.append('Gain that would justify the effort: %s%s' % (
        clip(gain['text'], 220), ' (assumption: the user was not there to answer)' if gain['source'] == 'assumption' else ''))
    ex = extras(work, intake, refs)
    L += ex['draft'] + ex['context']
    L.append('')
    if hist_lines:
        L += hist_lines + ['']
    L.append('## Prior art: %s' % pa['answer'])
    if _FULL or v4check.visible(work, {'tests.json': tj}):
        ledger = overlap.derive(work)
        L.append(overlap.summary(ledger))
    works = pa.get('closest_work') or []
    for c in top([c for c in works if c.get('kind') not in ('software', 'platform')], 3):
        L.append('- Closest: %s (%s), %s; differs: %s' % (clip(c.get('title'), 80), c.get('year', 'n.d.'),
                                                         refs.fmt(c.get('ref')), clip(c.get('what_differs'), 120)))
    for c in works:
        if c.get('kind') in ('software', 'platform'):
            L.append('- Closest tool/platform: %s [%s] (%s), %s; differs: %s' % (
                whole(c.get('title'), 80), c['kind'], c.get('year', 'n.d.'), refs.fmt(c.get('ref')),
                whole(c.get('what_differs'), 120)))
    if _FULL and pa.get('software_platform_search'):
        L.append('- Software/platform facet: %s' % json.dumps(pa['software_platform_search'], ensure_ascii=False))
    if pa['answer'] == 'Not found':
        L.append('- "Not found" is never a proof of absence. Searched: %s' % clip(pa.get('searched'), 160))
    else:
        L.append('- Searched: %s' % clip(pa.get('searched'), 160))
    if _R3:
        L += coverage_lines(pa)
    if _V2:
        L += plan_lines(work, refs, check.get(intake, 'vp', 'mode') == 'vp')
    mats = pa.get('materials') or {}
    parts = []
    for key, label in (('unexplained_anomalies', 'anomalies'), ('transferable_methods', 'transferable methods'),
                       ('contradictory_results', 'contradictory results')):
        items = [m for m in mats.get(key) or [] if isinstance(m, dict)]
        if items and _V2:                                   # v2: every item, whole
            parts.append('%s: %s' % (label, ' | '.join(clip(i.get('text'), 70) for i in items)))
        elif items:
            parts.append('%s: %s%s' % (label, clip(items[0].get('text'), 70),
                                       ' (+%d)' % (len(items) - 1) if len(items) > 1 else ''))
        else:
            parts.append('%s: none' % label)
    L.append('- Materials: ' + '; '.join(parts))
    if _R3:
        L += decisive_lines(work, refs, intake)
    L += ex['matter'] + ex['moment']
    L.append('')
    L.append('## Hypotheses')
    if _V2 and isinstance(hy.get('facets'), dict):
        fc = hy['facets']
        L.append('Facets: goal: %s; mechanism: %s%s' % (whole(fc.get('goal'), 120), whole(fc.get('mechanism'), 120), ''.join(
            '; %s: %s' % (k, whole(fc[k], 100)) for k in ('population', 'evaluation') if fc.get(k))))
    for h in top(hy['hypotheses'], 4):
        L.append('- %s (load-bearing): %s | for: %s | against: %s' % (
            h['id'], clip(h['statement'], 110), refs.many(h.get('for'), 2), refs.many(h.get('against'), 2)))
    for r in top(hy['rivals'], 2):
        L.append('- %s (rival%s): %s | why plausible: %s | for: %s' % (
            r['id'], operator_note(r), clip(r['statement'], 100), clip(r.get('why_plausible'), 80), refs.many(r.get('for'), 2)))
    for v in top(hy['repairable_variants'], 2):
        L.append('- %s (repairable variant%s): %s (repairs: %s)' % (v['id'], operator_note(v), clip(v['statement'], 100),
                                                                   clip(v.get('repairs'), 70)))
    if _V2:
        L += named_lines(work)
    L += ex['evidence']
    L.append('')
    order = tj['ranking']['order']
    by_id = {t['id']: t for t in tj['tests']}
    L.append('## Minimal tests, ranked by value of information for the next decision relative to cost')
    L.append('Order: %s. Basis: %s.' % (' > '.join(order), clip(tj['ranking'].get('basis'), 100)))
    has_v3 = ('prospective_not_applicable' in tj or any(
        any(key in t for key in ('pre_critique', 'start_action', 'readout_date')) or t.get('kind') == 'prospective' or
        any(key in t.get('sensitivity', {}) for key in ('minimum_useful_effect', 'power_at_minimum'))
        for t in tj['tests']))
    if has_v3:
        L.append(v3check.pitfalls_line(tj))
    L += v3check.prospective_lines(tj)
    if _FULL and tj.get('prospective_not_applicable'):
        L.append('Prospective not applicable: %s' % tj['prospective_not_applicable'])
    for tid in order:
        t = by_id[tid]
        di, rule, sens, feas, traps = (t['decisive_intervention'], t['decision_rule'], t['sensitivity'],
                                       t['feasibility'], t['traps'])
        # Pre-R3 cards without V3 fields keep their historical bytes.
        show_power = (_R3 or t.get('kind') == 'prospective' or 'pre_critique' in t or
                      'minimum_useful_effect' in sens or 'power_at_minimum' in sens)
        L.append('### %s: %s%s%s' % (tid, '%s: ' % _HEADS[tid] if _V2 and tid in _HEADS else '',
                                     clip(t['title'], 110), ' | ' + v3check.power_label(t, show_counts=not _V2 or has_v3) if show_power else ''))
        if _FULL:
            L.append('- Minimum-effect power basis: %s' % json.dumps(v3check.power_at_minimum(t), ensure_ascii=False))
            L.append('- Pre-critique checklist: %s' % json.dumps(t.get('pre_critique', 'missing [PITFALL-CHECK]'), ensure_ascii=False))
        if _V2:
            L += v2_test_lines(t)
        if _R3 and not _FULL:
            _r3_test_lines(L, t)
            continue
        L.append('- Competing: %s. Predictions: %s. Compatible with both: %s. Unexpected under both: %s' % (
            ' vs '.join(t['competing_hypotheses']), '; '.join(pred_text(p) for p in t['predictions']),
            bare(t['compatible_with_both'], 70), bare(t['unexpected_under_both'], 70)))
        L.append('- Decisive intervention (%s): %s' % (', '.join(di['kind']), clip(di['description'], 160)))
        eq = rule['equivalence']
        L.append('- Decision rule, fixed before observation: continue if %s; revise if %s; stop if %s; indeterminate if '
                 '%s. Equivalence: %s.' % (bare(rule['continue_if'], 90), bare(rule['revise_if'], 80),
                                           bare(rule['stop_if'], 80), bare(rule['indeterminate_if'], 60),
                                           'margin ' + clip(eq.get('margin'), 50) if eq.get('relevant')
                                           else 'not relevant (%s)' % clip(eq.get('why_not'), 50)))
        L.append('- Sensitivity: smallest useful effect %s; noise %s; replications %s; %s' % (
            clip(sens['smallest_useful_effect'], 60), clip(sens['expected_noise'], 60),
            clip(sens['replications'], 40), sim_text(sens)))
        L.append('- Feasibility: data %s; human time %s; compute %s; risk %s' % (
            clip(feas['data'], 70), clip(feas['human_time'], 40), clip(feas['compute'], 40),
            clip(feas['technical_risk'], 70)))
        pv, va, pc, ds = traps['proxy_vs_target'], traps['variants'], traps['positive_control'], traps['data_split']
        mc = ('; correction: %s' % clip(va.get('multiple_comparisons'), 50)) if va.get('multiple_comparisons') else ''
        L.append('- Traps: proxy %s vs target %s; %d variant(s) tested, choice fixed before (%s%s); positive control: %s; '
                 'design data (%s) kept apart from confirmation data (%s)' % (
                     clip(pv['proxy'], 40), clip(pv['target'], 40), va['number_tested'],
                     clip(va['selection_rule_fixed_before'], 50), mc, clip(pc['description'], 70),
                     clip(ds['design_data'], 40), clip(ds['confirmation_data'], 40)))
        l0 = t['l0_leakage_control']
        L.append('- L0 leakage control (C-075): %s' % (
            clip(l0.get('description'), 160) if l0.get('applicable') else 'not applicable: ' + clip(l0.get('why_not'), 120)))
        if _R3:                                  # the report holds the rest of the R3 fields of the test, nothing clipped
            L.append('- ' + scope_text(t))
            if power_text(t):
                L.append('- ' + power_text(t))
    if _R3 and not _FULL and _LEVEL >= 1:
        L.append('Traps, L0 control, sensitivity and feasibility of every test: %s' % check.REPORT)
    L.append('Scenarios:')
    for s in top(tj['ranking']['scenarios'], 3):
        L.append('- If %s, then %s (%s)' % (bare_whole(s.get('if'), 90), bare_whole(s.get('then'), 90), bare_whole(s.get('why'), 90)))
    L.append('')
    L.append('## Critique of the protocol: %s via %s' % (cr['critic_family'], cr['route']))
    if _FULL or v4check.visible(work, {'tests.json': tj}):
        revision = v4check.revision_line(work, {'tests.json': tj, 'critique.json': cr, 'intake.json': intake})
        if revision:
            L.append(revision)
    if cr['same_family']:
        L.append(SAME_FAMILY)
    L.append(whole(cr['summary'], 220))
    sc2 = cr.get('second_critique') if isinstance(cr.get('second_critique'), dict) else {}
    lifted = {v.get('item'): v.get('objection_lifted') for v in sc2.get('verdicts') or [] if isinstance(v, dict)}
    def action_of(i, it):
        a = it['response']['action']
        if _V2 and a == 'fixed':             # v2: a correction counts as fixed only with a proof and the second critique
            return a if lifted.get(i) == 'yes' and r3check.proof_problem(work, _DATA, it, check) is None else 'claimed fixed, not proven'
        return a
    if _R3:
        n_by = {}
        for i, it in enumerate(cr['items']):
            k = 'fixed (confirmed by the second critique)' if it['response']['action'] == 'fixed' and lifted.get(i) == 'yes' and \
                not (_V2 and action_of(i, it) != 'fixed') else action_of(i, it)
            n_by[k] = n_by.get(k, 0) + 1
        L.append('Items: %d (%s); a correction counts as fixed only with a proof and the confirmation of the second critique.'
                 % (len(cr['items']), ', '.join('%d %s' % (v, k) for k, v in sorted(n_by.items()))))
    pos = {id(x): i for i, x in enumerate(cr['items'])}
    if _R3 and not _FULL and _LEVEL >= 2:
        shown = [x for x in cr['items'] if action_of(pos[id(x)], x) in ('open', 'claimed fixed, not proven')]      # the others are in the report
    else:
        shown = top(cr['items'], 4)
    for it in shown:
        L.append('- [%s] %s %s: %s -> %s: %s' % (it['severity'], it['test'], it['category'], whole(it['text'], 100),
                                                action_of(pos[id(it)], it), clip(it['response'].get('note'), 80)))
    if len(cr['items']) > 4 and not (_FULL or _R3):
        L.append('- (+%d more in critique.json)' % (len(cr['items']) - 4))
    L.append('- ' + trap_verdicts_text(cr, order))
    if _FULL or _R3:
        L.append('- Raw answer of the critic: %s (sha256 %s)' % (cr.get('raw_output'), cr.get('raw_sha256')))
    else:
        L.append('- Raw answer of the critic: %s (sha256 %s...)' % (cr.get('raw_output'), str(cr.get('raw_sha256'))[:12]))
    L.append('')
    visible = v4check.visible(work, {'tests.json': tj})
    compact_codes = ('[REVISION]', '[OVERLAP-LEDGER]')
    if _V2:
        marks = _MARKS
    else:
        # Historical cards need no new artifact to disclose current omissions.
        _, warnings = check.run_all(work, with_card=False)
        marks = [w[len('mark: '):] for w in warnings if w.startswith('mark: ')]
    if not _FULL:
        # The tournament occupies one summary line; all its marks go to the report.
        marks = [m for m in marks if not m.startswith(('[TOURNAMENT]', '[REB-CRITIQUE]'))]
    inline = [m for m in marks if (not visible and m.startswith(compact_codes)) or
              (not _V2 and m.startswith(('[CRITIQUE]', '[RECO-OPEN]', '[DRAFT-REUSE?]')))]
    if inline:
        L.append('Marks: ' + ' | '.join(overlap.one_line(m) for m in inline))
    detailed = [m for m in marks if visible or not m.startswith(compact_codes)]
    if _V2 and detailed:
        L.append('## Marked, not blocking (tools/check.py): nothing below was removed; the researcher decides')
        L += ['- ' + m for m in detailed]
        L.append('')
    L.append('## Result')
    if res is None:
        L.append('No result.json yet: the plan has not been executed or declared plan only.')
    elif res['mode'] == 'plan only':
        L.append('Plan only: %s.' % clip(res.get('reason'), 160))
    else:
        ex = res.get('execution') or {}
        L.append('Executed %s with %s (exit code %s%s): %s Decision: **%s** (%s)' % (
            res['test'], res.get('engine'), ex.get('exit_code'), ', timed out' if ex.get('timed_out') else '',
            clip(res.get('observed'), 160), res.get('decision'), clip(res.get('decision_rule_applied'), 90)))
    L.append('')
    L.append('## Decision log')
    entries, _ = check.read_log(work)
    entries = entries or []
    for e in (entries if (_FULL or _R3) else entries[-4:]):
        L.append('- %s (%s, %s, %s): %s' % (e['phase'].capitalize(), e['test'], e['by'], e['utc'], whole(e['text'], 140)))
    if len(entries) > 4 and not (_FULL or _R3):
        L.append('- (+%d earlier entries in decision_log.jsonl)' % (len(entries) - 4))
    L.append('')
    offer = (not _FULL and any((work / name).is_file() for name in ('rebound.json', 'rebound_after.json'))
             and not tournament.present(work))
    # The offer replaces the final section separator, within the existing budget.
    sect = neighbour_lines(work, refs, UNLIMITED if (_FULL or _R3) else MAX_LINES - len(L) - 2)
    if sect:
        L += sect + ([] if offer else [''])
    if _FULL:
        data, _ = check.load(work)
        L += v3check.budget_lines(work, data)
        L += [''] + v4check.revision_report(work, data)
        L += [''] + overlap.report_lines(overlap.derive(work, data))
        L += [''] + rebound.report_lines(work)
        if tournament.present(work):
            L += [''] + tournament.report_lines(work)
    if offer:
        L.append(DEBATES_OFFER)
    L.append('<!-- frontier inputs sha256:%s -->' % check.inputs_fingerprint(work))
    return '\n'.join(L) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dir', nargs='?')
    ap.add_argument('--disclaimer', action='store_true', help='print the opening disclaimer only; do not run checks or write files')
    ap.add_argument('--lang', help='disclaimer language (en/fr; unsupported codes fall back to English)')
    a = ap.parse_args(argv)
    if a.disclaimer:
        intake = load(Path(a.dir), 'intake.json') if a.dir and a.lang is None else None
        print(disclaimer.get_disclaimer(a.lang if a.lang is not None else (intake or {}).get('language')))
        return 0
    if a.dir is None:
        ap.error('DIR is required unless --disclaimer is used')
    if a.lang is not None:
        ap.error('--lang is only used with --disclaimer; rendering uses intake.json language')
    work = Path(a.dir)
    probs, _ = check.run_all(work, with_card=False)
    if probs:
        print('card.py: refused, tools/check.py reports problems:')
        for p in probs:
            print(p)
        return 1
    try:
        text = render(work)
    except CardSizeError as error:
        print('card.py: refused, output format cannot fit the card (nothing written):')
        print(error)
        return 1
    probs = check.card_text_problems(work, text)
    if probs:
        print('card.py: refused, the card would not pass the card checks (nothing written):')
        for p in probs:
            print(p)
        return 1
    report = render(work, full=True)           # the complete report: same files, nothing clipped (after the card checks)
    out = work / check.CARD
    common.atomic_write(out, text)
    common.atomic_write(work / check.REPORT, report)
    print(out.resolve())
    print((work / check.REPORT).resolve())
    print('card.py is the LAST command of a run. After any later input edit or command that changes inputs, rerun card.py.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
