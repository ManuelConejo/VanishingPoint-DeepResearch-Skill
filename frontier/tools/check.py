#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Mechanical check of a Frontier working directory (SKILL.md, every step). Offline, no model, standard library.

Usage: check.py DIR [--json]
Exit code 0 = no problem, 1 = problems (listed one per line), 2 = usage error. Warnings (prefix `warning:`) never block.
The report starts with the note: "checks are structural; they do not prove scientific soundness". They check that every
box is filled, consistent and traceable (fingerprints, reruns, VP verdicts, dates), not that the science is right.

What it checks, by stable code (each problem line starts with its code):
  [MISSING] [JSON] [SCHEMA]  every required file is present, parses, and matches frontier/schemas/<file> (schema_lite.py);
                 required: intake.json prior_art.json hypotheses.json tests.json critique.json recommendation.json
                 decision_log.jsonl run.json; optional: result.json (absent = plan not yet decided), IDEA-CARD.md.
  [INTAKE]       idea in 1 to 3 sentences, domain, valid T, language, the gain that would justify the effort.
  [VP-MODE]      vp.mode "none" while tools/setup.py detects VP needs vp.none_reason (written, not a placeholder).
  [PRIOR-ART]    what was searched; Exists/Partially need the closest work, each with what differs; materials have text;
                 with VP, the answer equals the answer line of VP's PRIOR-ART.md (vp_prior_art_md) when it is given.
  [DISCLAIMER]   IDEA-CARD.md begins with the exact tools/disclaimer.py text for intake.json language (English fallback).
  [HEADER]       without VP: prior_art.json "header" and the card's reference warning, immediately after the disclaimer, are exactly
                 "References not verified (VP not installed)"; with VP that header must not be there.
  [HYPOTHESES]   2 to 4 load-bearing hypotheses, each with at least one reference for or against; >= 1 repairable variant;
                 unique ids.   [RIVAL] at least one plausible competing explanation.
  [GRID]         1 to 3 tests, each with the complete strong-inference grid (competing_hypotheses, predictions,
                 compatible_with_both, unexpected_under_both, decisive_intervention, sensitivity, decision_rule,
                 feasibility).
  [COMPETING]    >= 2 known hypothesis ids per test, at least one of them a rival R (a variant V alone is not a rival).
  [PRED]         one prediction per competing hypothesis, each with a direction, a numeric interval [low, high] and its
                 unit.   [PRED-IDENTICAL] two hypotheses predict the same interval.   [PRED-OVERLAP] two predicted
                 intervals overlap and compatible_with_both does not name the overlap (its two bounds, as numbers).
  [RULE]         continue_if / revise_if / stop_if / indeterminate_if filled, fixed_before_observation true, equivalence
                 declared, fixed_utc before the execution if executed.
  [L0]           llm_judges_history declared; when true, an L0 leakage control (C-075) is described.
  [TRAP]         the four traps, every text field written (no placeholder such as "n/a", "none", "tbd", "-", and at least
                 20 characters); proxy != target; design data != confirmation data; several variants tested => a
                 correction for multiple comparisons (variants.multiple_comparisons).
  [SIM]          sensitivity.simulation written by tools/sim.py (>= 2 scenarios), or simulation_not_applicable with a reason;
                 a simulation that does not distinguish the scenarios is a warning shown on the card.
  [SIM-LINK]     scenario names are competing hypotheses of the test, each effect lies in its predicted interval, and
                 decision_rule.thresholds equals the simulated rule.   [SIM-RERUN] the simulation is rerun from its
                 stored parameters (tools/sim.py rerun) and must give the same numbers.
  [RANK]         ranking: basis, order = the tests, explicit scenarios (if / then / why), and no number anywhere.
  [CRITIQUE]     same_family consistent with the families (config.json critic, FRONTIER_HOST_FAMILY,
                 FRONTIER_CRITIC_FAMILIES; aliases from config.json); the author is the configured host family; a
                 same-family critique only when no other family is configured, by the subagent route, with
                 no_independent_critic true; the raw answer of the critic kept in the directory (raw_output) with its
                 SHA-256 (raw_sha256), every item text and every trap-verdict reason found in it; items not empty, on known
                 tests; open methodological objections are marks; a verdict per test and per trap.
  [RESULT]       plan only + reason, or executed + test + observed + decision in continue|revise|stop|indeterminate.
  [PROOF]        an executed result carries before_fingerprint = the fingerprint of the test now in tests.json, and a
                 "before" of that test with that fingerprint was written before the execution started.
  [RECO]         reason in one sentence, no certification of novelty or value.
  [LOG]          decision_log.jsonl valid, at least one "before", every "after" preceded by a "before" of the same test.
  [REF-ABSENT] [REF-INVALID] [REF-MISSING] [REF-MISMATCH] [REF-CARD]  with VP: every reference names a VP run of
                 intake.json vp.runs and a claim id; its status is read in <run>/verdicts.json (ABSENT or INVALID fail,
                 no verdict fails; UNVERIFIED and SOURCE-UNAVAILABLE pass and are listed on the card); <run>/card.json is
                 required and the identifier must be the claim's source there.
  [VP-RUN]       each VP run of intake.json holds the gateway journal state/journal.jsonl (JSON lines, at least one call),
                 and every cited claim is in its card.json and its verdicts.json.
  [DATE]         every gateway journal entry of a VP run has T <= the T of intake.json; no reference dated after the year
                 of T (year of the reference, of the closest work, of card.json sources, or of STUDIES.json / result.json
                 of the VP run).
  [RUNLOG]       run.json valid (steps with utc, duration_s and cost_usd as numbers or "unknown").
  [BUDGET]       per idea, from run.json: at most config.json budget.vp_runs "vp_run" steps, budget.critiques "critique"
                 steps, budget.executions "execution" steps; each VP run of intake.json has its "vp_run" step; a critique
                 has its "critique" step; an executed result has its "execution" step.
  Rebound (optional files rebound.json = step 8, rebound_after.json = step 8-bis, schemas/rebound.json; nothing is
  checked when they are absent; thresholds in config.json "rebound"):
  [REB-STAGE]    stage matches the file, parent_idea is the idea of intake.json, step 8 has no after_* fields.
  [REB-OPERATOR] operator known, recurring_ingredient a boolean (true only for facet_recombination, analogy, literature_bridge:
                 the others are "not measured"), an analogy says what corresponds and what breaks, a bridge names its concept.
  [REB-MATERIAL] at least one material per idea: a reference with an id, or an entry that resolves (prior_art.json:...,
                 hypotheses.json:<id>, tests.json:<id>, result.json:<id>); an anomaly idea cites an anomaly/contradiction.
  [REB-STRUCT]   mechanism, hypothesis, test (one_line, variable, if_holds, if_fails), teaches and tradeoffs written (12
                 characters or more, no placeholder); unique ids N1.. (step 8) or B1.. (step 8-bis).
  [REB-PRIOR-ART] a prior-art check on EVERY idea (status, queries, scope; Exists/Partially: closest work with ref and
                 what_differs; Partially: difference); with VP a vp_run whose PRIOR-ART.md answer equals the status (lowering
                 to Insufficient search allowed); "uncontrolled" only when the budget of checks is used up. Round 2: with VP
                 one VP run per idea, every written query is a query of that run's gateway journal (state/journal.jsonl),
                 dated at most at prior_art.date; the closest works cite the idea's own VP run. Without VP the queries are
                 still written and each idea gets the warning "not verified: no VP".
  [REB-ORDER]    every prior-art date <= ranking.ranked_utc <= selection.decided_utc; a ranking or a choice needs the checks of
                 all ideas (registered search: queries, scope, date, not "uncontrolled"); ranking scenarios explicit; no
                 order imposed (prefer lists in canonical order, no ordinal wording: a lexical net, not a proof).
  [REB-CRITIQUE] (nonblocking mark) missing individual critiques, including older rebound files without any critique.
  [REB-REPAIR]   critique dates follow the latest prior-art check of all ideas; critique and repair dates precede ranking
                 and selection. Repair receipts have real UTC dates; identity, length and own-critique links stay valid.
  [REB-REF]      (warning) a reference of a rebound file that is UNVERIFIED, SOURCE-UNAVAILABLE or DISTORTED.
  [REB-QUOTA]    5 to 10 ideas (step 8), 2 to 4 (step 8-bis), at most 2 per operator.
  [REB-DUP]      duplicate_groups equals the grouping by mechanism, hypothesis, test and word overlap (tools/rebound.py);
                 possible duplicates are also a warning; ideas are never removed.
  [REB-FEAS]     "established" needs a named, reachable dataset or tool, or a number and its unit; else "not established".
  [REB-NOVELTY]  no number in an idea except feasibility.<element>.amount, none in the ranking, no field named score/rating/..,
                 no "novelty 8/10", no certification wording.
  [REB-SELECT]   at most 2 retained ideas, known ids, none both retained and rejected, none retained without the user.
  [REB-AFTER]    step 8-bis: after_test known, an "after" entry in the decision log, outcome consistent with result.json,
                 follow_up_kind fits the outcome.
  [REB-TREE]     IDEA-TREE.json (schema, unique ids, existing parents, no cycle) agrees with the selection; an absent tree or an
                 unregistered directory is a warning.
  [HEADER]       also for the rebound files (header without VP, none with VP).   [BUDGET]  also rebound_vp_run steps and checks
                 (config.json rebound.prior_art_checks_max per file, prior_art_checks_card_max per card); a recorded
                 individual critique needs its rebound_critique step, under config.json rebound_critiques_max.
  The references of the rebound files (materials, closest work, feasibility) go through the same VP checks as the others.
  History (step 0-bis "Already tried here"; history.json written by tools/history.py; nothing is checked when intake.json
  gives no project_dirs: the card then says "not checked"; thresholds in config.json "history"):
  [HISTORY-MISSING] project_dirs is given but history.json is absent.   [HISTORY-STALE] history.json was made for other
                 project folders than intake.json now names.   [HISTORY-QUERY] no "intake" query, no "tests" query (tests.json
                 exists), no "rebound" query (a rebound file exists), or a test / idea with no term "for" its id in its query.
  [HISTORY-OVERLAP] a test of tests.json or an idea of a rebound file overlaps a CLASSED passage of history.json (a term of the
                 entry or its synonyms in the text of the item, or a term "for" the item) and no valid internal_history item
                 cites a passage of each file concerned; "tried" passages and terms marked generic never block (a warning
                 lists the generic terms).   [HISTORY-CITE] an internal_history item (entry, cited = file:line of the entry,
                 verdict_quoted found in it, reopen_condition written in the entry or at reopen_condition_source file:line
                 read locally, condition_met of 40 characters or more, decision "kept") or an internal_history_removed note
                 (cited = file:line, read again in the project folder, what, why) is invalid.   [HISTORY-LEAK] text of history.json (a 5-word run of an excerpt, verdict
                 line or reopening condition, a file path, a project folder) found in a request: the gateway journal and
                 scope.md of a VP run, prior_art.json "searched", the queries and scope of the rebound checks, the
                 critique-pack; the words of the idea and of the query terms are not counted.
  Hybrid free draft (step 0-ter; nothing is checked when free_draft.md is absent):
  [DRAFT-MISSING] free_draft.md without draft_claims.json.   [DRAFT-EMPTY] fewer than 200 characters.   [DRAFT-STALE] the
                 SHA-256 of draft_claims.json, or of the "free_draft" step of run.json, is not the one of the current draft.
  [DRAFT-ORDER]  no "free_draft" step, or it comes after a VP run.   [DRAFT-QUOTE] a claim's quote is not a passage of the draft.
  [DRAFT-VERIFY] a "verified" claim without a VP reference (run + claim) or with an ABSENT / INVALID / missing verdict.
  [DRAFT-NOVP]   "verified" without VP.   [DRAFT-UNMARKED] an item of the draft (author-year reference, identifier, decimal
                 number or percentage; tools/hybrid.py) that a text field of the card files takes up has no claim covering it.
  [DRAFT-MARK]   an "unverified_memory" item is taken up without the literal "unverified (memory)" in that field.
  [DRAFT-REMOVED] a removed item is taken up anyway.
  mark [DRAFT-REUSE?] a partial lexical match suggests reuse; verify its meaning,
                 even when a draft quote is verified. Only whole quotes establish exact textual reuse in strict scans.
  Project context (step 0-quater): [CONTEXT-CONFIRM] an extracted key number not confirmed.   [CONTEXT-CITE] its cited file:line
                 is unreadable or does not hold the value.   [CONTEXT-SIM] a simulation claims a context value other than the
                 confirmed number.   [CONTEXT-LEAK] an excerpt of context_candidates.json in a request.   warning
                 [CONTEXT-POWER] the context has an n that a simulation ignores.
  Expected effects (step 2-bis, evidence_table.json): [EVID-COVER] a main lead with neither entry nor "no_evidence" note, or an
                 unknown lead.   [EVID-FIELD] sample, effect value and unit, or not_reported.   [EVID-SOURCE] a measured effect
                 without source (its reference goes through the VP checks).   [EVID-SIZE] needed_test_size absent, not
                 rerunnable, or different from the tools/sim.py --needed-n rerun.
  Matter and moment (step 1-bis, material.json, moment.json): [MAT-COVER] the main idea or a neighbouring idea has neither an
                 item nor a recorded "not found" search.   [MAT-FOR] unknown idea id.   [MAT-FIELD] licence missing.
                 [MAT-ENVELOPE] a gateway envelope missing, changed, or whose licence or last activity differs from the item.
                 [MAT-OPTIONAL] a source neither used nor skipped with a reason.   [MAT-CATALOGUE] a catalogue or directions
                 match that is not in the file.   [DATE] an activity, an envelope or a gateway journal after T.   warning
                 [MAT-HOST] an item found by the host's own search, not verified.   [MOMENT-SERIES] fewer than 4 totals, dates
                 not increasing, totals decreasing, last date after T.   [MOMENT-ENVELOPE] total or date differs from the saved
                 answer.   [MOMENT-READING] periods, thresholds or reading not recomputable from the totals.
  [REPORT-STALE] IDEA-REPORT.md differs from the report rendered from the current files (stale or edited by hand).
  [CARD]         IDEA-CARD.md holds on one page (at most 80 lines).   [CARD-STALE] the card's inputs fingerprint
                 (<!-- frontier inputs sha256:... -->) differs from the files: regenerate it with tools/card.py.

Import: problems(dir) -> [str]; warnings(dir) -> [str]; run_all(dir) -> (problems, warnings);
        reference_statuses(dir) -> {identifier: status}; ref_status(dir, ref) -> status or None;
        unverified_references(dir) -> [(identifier, status)]; inputs_fingerprint(dir) -> hex;
        card_text_problems(dir, text) -> [str]
"""
import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ written in the skill directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import disclaimer  # noqa: E402
import guards  # noqa: E402
import hybrid  # noqa: E402
import matter  # noqa: E402
import r3check  # noqa: E402
import rebound  # noqa: E402
import schema_lite  # noqa: E402
import setup  # noqa: E402
import sim  # noqa: E402
import v2check  # noqa: E402
import v4check  # noqa: E402
import tournament  # noqa: E402

FRONTIER = Path(__file__).resolve().parent.parent
NEW_FILES = ['draft_claims.json', 'evidence_table.json', 'material.json', 'moment.json']   # optional (AM1 round)
NEW_INPUTS = ['free_draft.md', 'draft_claims.json', 'evidence_table.json', 'material.json', 'moment.json',
              'context_candidates.json', 'decisive_claims.json', 'framing.json', 'research_plan.json', 'named_elements.json',
              'test_revision.json', 'overlap_ledger.json', tournament.LEGACY_JOURNAL, tournament.JOURNAL]  # count in the card fingerprint when present
REPORT = 'IDEA-REPORT.md'
DRAFT_MIN_CHARS = 200
SCHEMAS = FRONTIER / 'schemas'
HEADER = 'References not verified (VP not installed)'
NOTE = 'Note: checks are structural; they do not prove scientific soundness.'
REQUIRED = ['intake.json', 'prior_art.json', 'hypotheses.json', 'tests.json', 'critique.json', 'recommendation.json']
OPTIONAL = ['result.json']
REBOUND_FILES = list(rebound.FILES)             # rebound.json (step 8), rebound_after.json (step 8-bis): optional
SCHEMA_OF = {'rebound_after.json': 'rebound.json'}
LOG = 'decision_log.jsonl'
RUN = 'run.json'
CARD = 'IDEA-CARD.md'
CARD_INPUTS = ['intake.json', 'prior_art.json', 'hypotheses.json', 'tests.json', 'critique.json', 'result.json',
               'recommendation.json', LOG]
CARD_FP = re.compile(r'<!-- frontier inputs sha256:([0-9a-f]{64}) -->')
CARD_MAX_LINES = 80
INTERVENTIONS = ('ablation', 'negative_control', 'positive_control', 'permutation', 'randomisation', 'factorial')
DECISIONS = ('continue', 'revise', 'stop', 'indeterminate')
OK_STATUSES = ('FOUND', 'DISTORTED', 'SOURCE-UNAVAILABLE', 'UNVERIFIED')
UNVERIFIED_STATUSES = ('SOURCE-UNAVAILABLE', 'UNVERIFIED')
STATUS_RANK = {'FOUND': 0, 'DISTORTED': 1, 'SOURCE-UNAVAILABLE': 2, 'UNVERIFIED': 3, 'ABSENT': 4, 'INVALID': 5}
TRAPS = ('proxy_vs_target', 'variants', 'positive_control', 'data_split')
TRAP_VERDICTS = ('addressed', 'not_addressed', 'unclear')
CERTIFY = re.compile(r'\b(is|are)\s+(truly\s+|really\s+)?(novel|new|original|valuable)\b|\bcertif|\bguarantee'
                     r'|\bcertain(ly)?\b|\bprove[sdn]?\b|\bproving\b|\bdefinitely\b|\bnovelty is\b'
                     r'|\bunprecedented\b|\bground-?breaking\b|\bfirst[- ]ever\b|\bnever been (done|tried)\b'
                     r'|\bworld[- ]first\b', re.I)
SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9"(])')
NUMBER = re.compile(r'-?[0-9]+(?:\.[0-9]+)?')
NON_ID_FIELDS = ('title', 'year', 'url', 'authors', 'venue')
PRIOR_ART_LINE = re.compile(r'<!-- prior_art\.py inputs sha256:[0-9a-f]* answer:([A-Z ]+?) -->')
PRIOR_ART_ANSWERS = {'EXISTS': 'Exists', 'PARTIALLY': 'Partially', 'NOT FOUND': 'Not found'}


# critique categories that are factual or arithmetic errors: they block while open (everything else is a mark)
FACT_CATEGORIES = ('factual_error', 'arithmetic_error')

def text(x):
    return x.strip() if isinstance(x, str) else ''


def sentences(s):
    s = text(s)
    return [p for p in SENTENCE_SPLIT.split(s) if p.strip()] if s else []


def norm(s):
    return re.sub(r'\s+', ' ', text(s).lower())


def parse_utc(s):
    try:
        return datetime.datetime.strptime(text(s), '%Y-%m-%dT%H:%M:%SZ')
    except ValueError:
        return None


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def year_of(x):
    m = re.match(r'^\s*([0-9]{4})', str(x)) if x is not None else None
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- loading


def load(work):
    data, probs = {}, []
    for name in REQUIRED + OPTIONAL + REBOUND_FILES + NEW_FILES:
        p = work / name
        if not p.exists():
            if name in REQUIRED:
                probs.append('[MISSING] %s: required file absent' % name)
            continue
        try:
            data[name] = read_json(p)
            if name == 'material.json':
                data[name] = matter.normalize_material(data[name])
        except (ValueError, UnicodeDecodeError) as e:
            probs.append('[JSON] %s: %s' % (name, e))
            continue
        schema = read_json(SCHEMAS / SCHEMA_OF.get(name, name))
        for e in schema_lite.validate(data[name], schema):
            probs.append('[SCHEMA] %s: %s' % (name, e))
    return data, probs


def get(d, *keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def vp_mode(data):
    return get(data.get('intake.json'), 'vp', 'mode') or 'none'


def intake_year(data):
    return year_of(get(data.get('intake.json'), 'T'))


# ---------------------------------------------------------------- steps


def check_intake(d, P):
    if not isinstance(d, dict):
        return
    n = len(sentences(d.get('idea')))
    if not 1 <= n <= 3:
        P.append('[INTAKE] intake.json: idea must hold in 1 to 3 sentences (found %d)' % n)
    if not text(d.get('domain')):
        P.append('[INTAKE] intake.json: domain is empty')
    try:
        datetime.date.fromisoformat(text(d.get('T')))
    except ValueError:
        P.append('[INTAKE] intake.json: T is not a valid date YYYY-MM-DD')
    if not text(get(d, 'justifying_gain', 'text')):
        P.append('[INTAKE] intake.json: justifying_gain.text is empty (what new knowledge or capability would justify '
                 'the effort? if the user is absent, write an assumption with source "assumption")')
    if get(d, 'vp', 'mode') == 'vp' and not get(d, 'vp', 'runs'):
        P.append('[INTAKE] intake.json: vp.mode is "vp" but vp.runs names no VP run')


def check_vp_mode(d, P):
    if not isinstance(d, dict) or get(d, 'vp', 'mode') != 'none':
        return
    found = setup.detect_vp()
    if found.get('found') and common.is_placeholder(get(d, 'vp', 'none_reason')):
        P.append('[VP-MODE] intake.json: VP is installed (%s) but vp.mode is "none": use VP, or write why not in '
                 'vp.none_reason (at least 20 characters)' % found.get('dir'))


def check_prior_art(work, d, mode, P):
    if not isinstance(d, dict):
        return
    answer = d.get('answer')
    if not text(d.get('searched')):
        P.append('[PRIOR-ART] prior_art.json: "searched" must say what was searched (a "Not found" is never a proof of '
                 'absence, and means nothing without it)')
    closest = d.get('closest_work') if isinstance(d.get('closest_work'), list) else []
    if answer in ('Exists', 'Partially') and not closest:
        P.append('[PRIOR-ART] prior_art.json: answer %r needs at least one closest work' % answer)
    for i, c in enumerate(closest):
        if not isinstance(c, dict):
            continue
        # A missing distinction is methodological uncertainty, not a factual
        # error. V4 retains the overlap and emits [OVERLAP-LEDGER] as a mark.
        if not text(c.get('title')):
            P.append('[PRIOR-ART] prior_art.json: closest_work[%d].title is empty' % i)
    mats = d.get('materials') if isinstance(d.get('materials'), dict) else {}
    for key, items in mats.items():
        for i, m in enumerate(items if isinstance(items, list) else []):
            if isinstance(m, dict) and not text(m.get('text')):
                P.append('[PRIOR-ART] prior_art.json: materials.%s[%d].text is empty' % (key, i))
    header = d.get('header')
    if mode != 'vp' and header != HEADER:
        P.append('[HEADER] prior_art.json: without VP, "header" must be exactly %r' % HEADER)
    if mode == 'vp' and header is not None:
        P.append('[HEADER] prior_art.json: VP is used (intake.json vp.mode = "vp"); remove the "header" field')
    md = d.get('vp_prior_art_md')
    if mode == 'vp' and not text(md):
        P.append('[PRIOR-ART] prior_art.json: VP is used: vp_prior_art_md (the PRIOR-ART.md of the VP prior-art run) is '
                 'required')
    if mode == 'vp' and text(md):
        p = Path(md) if Path(md).is_absolute() else work / md
        try:
            first = p.read_text(encoding='utf-8')
        except OSError:
            P.append('[PRIOR-ART] prior_art.json: vp_prior_art_md %s cannot be read' % md)
            return
        m = PRIOR_ART_LINE.search(first)
        vp_answer = PRIOR_ART_ANSWERS.get(m.group(1).strip()) if m else None
        if vp_answer is None:
            P.append('[PRIOR-ART] prior_art.json: %s has no answer line of VP tools/prior_art.py (or a pending one)' % md)
        elif vp_answer != answer:
            P.append('[PRIOR-ART] prior_art.json: answer %r differs from VP PRIOR-ART.md %r; copy it, never upgrade or '
                     'soften it' % (answer, vp_answer))


def check_hypotheses(d, P):
    ids = {'H': set(), 'R': set(), 'V': set()}
    if not isinstance(d, dict):
        return ids
    hyps = d.get('hypotheses') if isinstance(d.get('hypotheses'), list) else []
    rivals = d.get('rivals') if isinstance(d.get('rivals'), list) else []
    variants = d.get('repairable_variants') if isinstance(d.get('repairable_variants'), list) else []
    if not 2 <= len(hyps) <= 4:
        P.append('[HYPOTHESES] hypotheses.json: 2 to 4 load-bearing hypotheses expected (found %d)' % len(hyps))
    seen = []
    for h in hyps:
        if not isinstance(h, dict):
            continue
        seen.append(h.get('id'))
        if not text(h.get('statement')):
            P.append('[HYPOTHESES] hypotheses.json: %s: empty statement' % h.get('id'))
        n = sum(len(h.get(k)) for k in ('for', 'against') if isinstance(h.get(k), list))
        if n == 0:
            P.append('[HYPOTHESES] hypotheses.json: %s: no reference for or against' % h.get('id'))
        ids['H'].add(h.get('id'))
    if not rivals:
        P.append('[RIVAL] hypotheses.json: at least one plausible competing explanation (rivals) is required')
    for r in rivals:
        if not isinstance(r, dict):
            continue
        seen.append(r.get('id'))
        if not text(r.get('statement')) or not text(r.get('why_plausible')):
            P.append('[RIVAL] hypotheses.json: %s: statement and why_plausible must be filled' % r.get('id'))
        ids['R'].add(r.get('id'))
    if not variants:
        P.append('[HYPOTHESES] hypotheses.json: at least one repairable variant of the idea is required')
    for v in variants:
        if not isinstance(v, dict):
            continue
        seen.append(v.get('id'))
        if not text(v.get('statement')) or not text(v.get('repairs')):
            P.append('[HYPOTHESES] hypotheses.json: %s: statement and repairs must be filled' % v.get('id'))
        ids['V'].add(v.get('id'))
    dups = sorted({str(x) for x in seen if seen.count(x) > 1})
    if dups:
        P.append('[HYPOTHESES] hypotheses.json: duplicate ids %s' % ', '.join(dups))
    return ids


def interval(p):
    iv = p.get('interval') if isinstance(p, dict) else None
    if isinstance(iv, list) and len(iv) == 2 and all(is_num(x) for x in iv) and iv[0] <= iv[1]:
        return float(iv[0]), float(iv[1])
    return None


def names_overlap(txt, lo, hi):
    nums = [float(x) for x in NUMBER.findall(text(txt))]
    return any(abs(x - lo) < 1e-9 for x in nums) and any(abs(x - hi) < 1e-9 for x in nums)


def check_predictions(tid, t, competing, P):
    preds = t.get('predictions')
    if not isinstance(preds, list) or not preds:
        P.append('[GRID] tests.json: %s: predictions missing or empty' % tid)
        return
    covered = set()
    for i, p in enumerate(preds):
        if not isinstance(p, dict):
            continue
        h = p.get('hypothesis')
        covered.add(h)
        if h not in competing:
            P.append('[PRED] tests.json: %s: prediction %d is for %r, not one of the competing hypotheses' % (tid, i, h))
        if not text(p.get('direction')):
            P.append('[PRED] tests.json: %s: prediction for %s has no direction' % (tid, h))
        if interval(p) is None:
            P.append('[PRED] tests.json: %s: prediction for %s needs a numeric interval [low, high] with low <= high'
                     % (tid, h))
        if not text(p.get('unit')):
            P.append('[PRED] tests.json: %s: prediction for %s needs the unit of its interval ("unit")' % (tid, h))
    for h in competing:
        if h not in covered:
            P.append('[PRED] tests.json: %s: no prediction for competing hypothesis %s' % (tid, h))
    good = [p for p in preds if isinstance(p, dict) and interval(p)]
    for i in range(len(good)):
        for j in range(i + 1, len(good)):
            a, b = good[i], good[j]
            ia, ib = interval(a), interval(b)
            if ia == ib:
                P.append('[PRED-IDENTICAL] tests.json: %s: %s and %s predict the same interval %s; the test cannot '
                         'discriminate them' % (tid, a.get('hypothesis'), b.get('hypothesis'), list(ia)))
            elif ia[0] <= ib[1] and ib[0] <= ia[1]:
                lo, hi = max(ia[0], ib[0]), min(ia[1], ib[1])
                if not names_overlap(t.get('compatible_with_both'), lo, hi):
                    P.append('[PRED-OVERLAP] tests.json: %s: the intervals of %s and %s overlap on [%g, %g]; separate '
                             'them, or name that overlap (both bounds) in compatible_with_both'
                             % (tid, a.get('hypothesis'), b.get('hypothesis'), lo, hi))


def check_sim(tid, t, sens, competing, P, W):
    simb = sens.get('simulation')
    if simb is None:
        if not text(sens.get('simulation_not_applicable')):
            P.append('[SIM] tests.json: %s: sensitivity needs a simulation by tools/sim.py or '
                     'simulation_not_applicable with a reason' % tid)
        return
    if not isinstance(simb, dict) or simb.get('tool') != 'frontier/sim.py':
        P.append('[SIM] tests.json: %s: sensitivity.simulation must be the JSON output of tools/sim.py' % tid)
        return
    sc = simb.get('scenarios')
    if not isinstance(sc, list) or len(sc) < 2:
        P.append('[SIM] tests.json: %s: the simulation needs at least two scenarios' % tid)
        return
    if not isinstance(simb.get('seed'), int) or not isinstance(simb.get('distinguishes'), bool):
        P.append('[SIM] tests.json: %s: the simulation lacks its seed or its "distinguishes" verdict' % tid)
        return
    # link to the test (R41)
    preds = {p.get('hypothesis'): interval(p) for p in t.get('predictions') or [] if isinstance(p, dict)}
    for s in sc:
        if not isinstance(s, dict):
            continue
        name = s.get('name')
        if name not in competing:
            P.append('[SIM-LINK] tests.json: %s: simulation scenario %r is not a competing hypothesis of the test'
                     % (tid, name))
            continue
        iv = preds.get(name)
        eff = s.get('effect')
        if iv and (not is_num(eff) or not iv[0] - 1e-12 <= eff <= iv[1] + 1e-12):
            P.append('[SIM-LINK] tests.json: %s: scenario %s simulates effect %r, outside the interval %s that %s '
                     'predicts' % (tid, name, eff, list(iv), name))
    th = get(t, 'decision_rule', 'thresholds')
    rule = simb.get('rule') if isinstance(simb.get('rule'), dict) else {}
    if not isinstance(th, dict):
        P.append('[SIM-LINK] tests.json: %s: decision_rule.thresholds (continue_if_lower_above, stop_if_upper_below) is '
                 'required with a simulation: the rule simulated must be the rule fixed' % tid)
    else:
        for k in ('continue_if_lower_above', 'stop_if_upper_below'):
            if not is_num(th.get(k)) or not is_num(rule.get(k)) or abs(th[k] - rule[k]) > 1e-12:
                P.append('[SIM-LINK] tests.json: %s: decision_rule.thresholds.%s = %r but the simulation used %r'
                         % (tid, k, th.get(k), rule.get(k)))
    # rerun (R40)
    try:
        fresh = sim.rerun(simb)
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        P.append('[SIM-RERUN] tests.json: %s: the simulation cannot be rerun from its stored parameters (%s)' % (tid, e))
        return
    diffs = sim.compare(simb, fresh)
    if diffs:
        P.append('[SIM-RERUN] tests.json: %s: rerunning tools/sim.py with the stored parameters gives other numbers '
                 '(%s); write the simulation with sim.py --write-into, never by hand' % (tid, '; '.join(diffs[:3])))
        return
    if not simb['distinguishes']:
        W.append('[SIM] tests.json: %s: the simulation does NOT distinguish the scenarios (lowest probability of the '
                 'expected decision %s); the card says so' % (tid, simb.get('min_p_expected')))


def check_rule(tid, rule, started, P):
    for b in ('continue_if', 'revise_if', 'stop_if', 'indeterminate_if'):
        if not text(rule.get(b)):
            P.append('[RULE] tests.json: %s: decision_rule.%s is empty' % (tid, b))
    if rule.get('fixed_before_observation') is not True:
        P.append('[RULE] tests.json: %s: decision_rule.fixed_before_observation must be true' % tid)
    eq = rule.get('equivalence')
    if not isinstance(eq, dict) or not isinstance(eq.get('relevant'), bool):
        P.append('[RULE] tests.json: %s: decision_rule.equivalence must declare "relevant" (true/false)' % tid)
    elif eq['relevant'] and not text(eq.get('margin')):
        P.append('[RULE] tests.json: %s: an equivalence test needs its margin' % tid)
    elif not eq['relevant'] and not text(eq.get('why_not')):
        P.append('[RULE] tests.json: %s: say why an equivalence test is not relevant (why_not)' % tid)
    fixed = parse_utc(rule.get('fixed_utc'))
    if fixed and started and fixed > started:
        P.append('[RULE] tests.json: %s: the rule was fixed (%s) after the execution started' % (tid, rule.get('fixed_utc')))


def check_l0(tid, t, P):
    flag = t.get('llm_judges_history')
    l0 = t.get('l0_leakage_control')
    if not isinstance(flag, bool):
        P.append('[L0] tests.json: %s: declare llm_judges_history (true when a language model judges on history)' % tid)
        return
    if not isinstance(l0, dict):
        P.append('[L0] tests.json: %s: l0_leakage_control missing' % tid)
        return
    if flag:
        if l0.get('applicable') is not True or not text(l0.get('description')):
            P.append('[L0] tests.json: %s: a language model judges on history: an L0 leakage control (C-075) must be '
                     'described' % tid)
    elif l0.get('applicable') is True:
        if not text(l0.get('description')):
            P.append('[L0] tests.json: %s: l0_leakage_control.description is empty' % tid)
    elif not text(l0.get('why_not')):
        P.append('[L0] tests.json: %s: l0_leakage_control.why_not is empty' % tid)


TRAP_FIELDS = {
    'proxy_vs_target': ('proxy', 'target', 'how_kept_apart'),
    'variants': ('selection_rule_fixed_before',),
    'positive_control': ('description', 'distinguishes_bug_from_refutation'),
    'data_split': ('design_data', 'confirmation_data', 'separation'),
}


def check_traps(tid, traps, P):
    if not isinstance(traps, dict):
        P.append('[TRAP] tests.json: %s: traps missing (proxy_vs_target, variants, positive_control, data_split)' % tid)
        return
    for trap, fields in TRAP_FIELDS.items():
        tr = traps.get(trap)
        if not isinstance(tr, dict):
            P.append('[TRAP] tests.json: %s: trap %s missing' % (tid, trap))
            continue
        extra = [k for k, v in tr.items() if isinstance(v, str) and k not in fields]
        for f in list(fields) + extra:
            v = tr.get(f)
            if not text(v):
                P.append('[TRAP] tests.json: %s: traps.%s.%s is empty' % (tid, trap, f))
            elif common.is_placeholder(v):
                P.append('[TRAP] tests.json: %s: traps.%s.%s = %r is a placeholder or shorter than 20 characters: say '
                         'how this trap is handled' % (tid, trap, f, v))
        if trap == 'variants':
            n = tr.get('number_tested')
            if not isinstance(n, int) or isinstance(n, bool) or n < 1:
                P.append('[TRAP] tests.json: %s: traps.variants.number_tested must be an integer >= 1' % tid)
            elif n > 1 and 'multiple_comparisons' not in extra:
                P.append('[TRAP] tests.json: %s: %d variants are tested: traps.variants.multiple_comparisons must name '
                         'the correction for multiple comparisons' % (tid, n))
        if trap == 'proxy_vs_target' and text(tr.get('proxy')) and norm(tr.get('proxy')) == norm(tr.get('target')):
            P.append('[TRAP] tests.json: %s: proxy and target are the same; name the target the proxy stands for' % tid)
        if trap == 'data_split' and text(tr.get('design_data')) and \
                norm(tr.get('design_data')) == norm(tr.get('confirmation_data')):
            P.append('[TRAP] tests.json: %s: design data reused as confirmation data' % tid)


def _numbers(x, path=''):
    if isinstance(x, bool):
        return []
    if isinstance(x, (int, float)):
        return [path or 'ranking']
    if isinstance(x, dict):
        return [p for k, v in x.items() for p in _numbers(v, '%s.%s' % (path, k) if path else k)]
    if isinstance(x, list):
        return [p for i, v in enumerate(x) for p in _numbers(v, '%s[%d]' % (path, i))]
    return []


def check_ranking(r, test_ids, P):
    if not isinstance(r, dict):
        P.append('[RANK] tests.json: ranking missing')
        return
    nums = _numbers(r)
    if nums:
        P.append('[RANK] tests.json: no numeric score in the ranking (found at %s); use explicit scenarios'
                 % ', '.join('ranking.' + n for n in nums))
    if not text(r.get('basis')):
        P.append('[RANK] tests.json: ranking.basis is empty')
    order = r.get('order')
    if not isinstance(order, list) or sorted(map(str, order)) != sorted(map(str, test_ids)) or len(set(order)) != len(order):
        P.append('[RANK] tests.json: ranking.order must list every test once')
    sc = r.get('scenarios')
    if not isinstance(sc, list) or not sc:
        P.append('[RANK] tests.json: ranking.scenarios: at least one explicit scenario')
        return
    for i, s in enumerate(sc):
        if not isinstance(s, dict):
            continue
        for f in ('if', 'then', 'why'):
            if not text(s.get(f)):
                P.append('[RANK] tests.json: ranking.scenarios[%d].%s is empty' % (i, f))


def check_tests(d, ids, executed, P, W):
    if not isinstance(d, dict):
        return []
    tests = d.get('tests') if isinstance(d.get('tests'), list) else []
    primary = [t for t in tests if not isinstance(t, dict) or t.get('kind') != 'prospective']
    if not 1 <= len(tests) or len(primary) > 3:
        P.append('[GRID] tests.json: 1 to 3 primary tests expected (found %d primary, %d total); prospective companions may run alongside' %
                 (len(primary), len(tests)))
    elif not primary:
        W.append('mark: [GRID-PRIMARY] tests.json: only prospective tests (%d); no primary test decides now' % len(tests))
    if len(tests) - len(primary) > 1:
        W.append('mark: [PROSPECTIVE] tests.json: at most one prospective companion expected (found %d); all tests remain visible' %
                 (len(tests) - len(primary)))
    known = ids['H'] | ids['R'] | ids['V']
    tids = []
    for t in tests:
        if not isinstance(t, dict):
            continue
        tid = t.get('id', '?')
        tids.append(tid)
        started = None
        if executed and get(executed, 'test') == tid:
            started = parse_utc(get(executed, 'execution', 'started_utc'))
        for f in ('compatible_with_both', 'unexpected_under_both'):
            if not text(t.get(f)):
                P.append('[GRID] tests.json: %s: %s missing or empty' % (tid, f))
        comp = t.get('competing_hypotheses')
        if not isinstance(comp, list):
            P.append('[GRID] tests.json: %s: competing_hypotheses missing' % tid)
            comp = []
        else:
            if len(set(comp)) < 2:
                P.append('[COMPETING] tests.json: %s: at least two competing hypotheses' % tid)
            unknown = [c for c in comp if c not in known]
            if unknown:
                P.append('[COMPETING] tests.json: %s: unknown hypothesis ids %s' % (tid, ', '.join(map(str, unknown))))
            if not any(c in ids['R'] for c in comp):
                P.append('[COMPETING] tests.json: %s: the test must pit the idea against at least one rival explanation '
                         '(R); a repairable variant (V) alone is not a rival' % tid)
        check_predictions(tid, t, comp, P)
        di = t.get('decisive_intervention')
        if not isinstance(di, dict):
            P.append('[GRID] tests.json: %s: decisive_intervention missing' % tid)
        else:
            kinds = di.get('kind') if isinstance(di.get('kind'), list) else []
            if not kinds or any(k not in INTERVENTIONS for k in kinds):
                P.append('[GRID] tests.json: %s: decisive_intervention.kind must list one or more of %s'
                         % (tid, ', '.join(INTERVENTIONS)))
            if not text(di.get('description')):
                P.append('[GRID] tests.json: %s: decisive_intervention.description is empty' % tid)
        sens = t.get('sensitivity')
        if not isinstance(sens, dict):
            P.append('[GRID] tests.json: %s: sensitivity missing' % tid)
        else:
            for f in ('smallest_useful_effect', 'expected_noise', 'replications'):
                v = sens.get(f)
                ok = (isinstance(v, int) and not isinstance(v, bool) and v > 0) or bool(text(v))
                if not ok:
                    P.append('[GRID] tests.json: %s: sensitivity.%s missing or empty' % (tid, f))
            check_sim(tid, t, sens, comp, P, W)
        rule = t.get('decision_rule')
        if not isinstance(rule, dict):
            P.append('[GRID] tests.json: %s: decision_rule missing' % tid)
        else:
            check_rule(tid, rule, started, P)
        feas = t.get('feasibility')
        if not isinstance(feas, dict):
            P.append('[GRID] tests.json: %s: feasibility missing' % tid)
        else:
            for f in ('data', 'human_time', 'compute', 'technical_risk'):
                if not text(feas.get(f)):
                    P.append('[GRID] tests.json: %s: feasibility.%s missing or empty' % (tid, f))
        check_l0(tid, t, P)
        check_traps(tid, t.get('traps'), P)
    dups = sorted({str(x) for x in tids if tids.count(x) > 1})
    if dups:
        P.append('[GRID] tests.json: duplicate test ids %s' % ', '.join(dups))
    check_ranking(d.get('ranking'), tids, P)
    return tids


# ---------------------------------------------------------------- critique


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            for s in _strings(v):
                yield s
    elif isinstance(x, list):
        for v in x:
            for s in _strings(v):
                yield s


def raw_corpus(raw_bytes):
    """Whitespace-normalised text of the critic's raw answer, plus its decoded JSON strings when it is JSON."""
    raw = raw_bytes.decode('utf-8', 'replace')
    parts = [raw]
    for candidate in (raw, raw[raw.find('{'):raw.rfind('}') + 1] if '{' in raw else ''):
        try:
            parts.extend(_strings(json.loads(candidate)))
            break
        except ValueError:
            continue
    return '\n'.join(norm(p) for p in parts)


def check_raw_output(work, d, P):
    """(corpus or None). The raw answer exists inside the directory and matches its SHA-256."""
    rel = d.get('raw_output')
    if not text(rel):
        P.append('[CRITIQUE] critique.json: raw_output (the critic\'s raw answer, kept in this directory) is required')
        return None
    rp = Path(rel)
    if rp.is_absolute() or '..' in rp.parts:
        P.append('[CRITIQUE] critique.json: raw_output %r must be a path inside the working directory' % rel)
        return None
    p = work / rp
    try:
        inside = p.resolve().relative_to(work.resolve()) is not None
    except ValueError:
        inside = False
    if not inside or p.is_symlink() or not p.is_file():
        P.append('[CRITIQUE] critique.json: raw_output %s is missing (or a link, or outside the directory)' % rel)
        return None
    data = p.read_bytes()
    if hashlib.sha256(data).hexdigest() != d.get('raw_sha256'):
        P.append('[CRITIQUE] critique.json: raw_sha256 does not match %s: the raw answer was changed after its receipt '
                 '(tools/pack_critique.py --receipt)' % rel)
    return raw_corpus(data)


def check_critique(work, d, mode, test_ids, P, W):
    if not isinstance(d, dict):
        return
    cfg = common.config()
    author, critic = common.family(d.get('author_family'), cfg), common.family(d.get('critic_family'), cfg)
    same = author == critic
    if isinstance(d.get('same_family'), bool) and d['same_family'] != same:
        P.append('[CRITIQUE] critique.json: same_family is %s but author %r and critic %r are %s'
                 % (d['same_family'], d.get('author_family'), d.get('critic_family'),
                    'the same family' if same else 'different families'))
    host = cfg['critic'].get('host_family')
    if text(host) and common.family(host, cfg) != author:
        P.append('[CRITIQUE] critique.json: author_family %r is not the host family %r (config.json critic.host_family '
                 'or FRONTIER_HOST_FAMILY)' % (d.get('author_family'), host))
    configured = [common.family(f, cfg) for f in cfg['critic'].get('families') or []]
    others = sorted({f for f in configured if f and f != author})
    if same:
        if others:
            P.append('[CRITIQUE] critique.json: a critic of another family is configured (%s): a same-family critique '
                     'is refused' % ', '.join(others))
        if d.get('route') != 'subagent':
            P.append('[CRITIQUE] critique.json: a same-family critique is done by a sub-agent (route "subagent")')
        if d.get('no_independent_critic') is not True:
            P.append('[CRITIQUE] critique.json: a same-family critique must declare no_independent_critic: true (the '
                     'card then says "Critique: same family (no independent critic available)")')
    elif configured and critic not in configured:
        W.append('[CRITIQUE] critique.json: critic family %r is not among the configured families (%s)'
                 % (d.get('critic_family'), ', '.join(configured)))
    if d.get('route') == 'vp-contradictor' and mode != 'vp':
        P.append('[CRITIQUE] critique.json: route "vp-contradictor" needs VP (intake.json vp.mode = "vp")')
    items = d.get('items') if isinstance(d.get('items'), list) else []
    if not items:
        P.append('[CRITIQUE] critique.json: items is empty: the critic returns at least one item')
    corpus = check_raw_output(work, d, P)
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        if it.get('test') != 'all' and it.get('test') not in test_ids:
            P.append('[CRITIQUE] critique.json: items[%d].test %r is not a test of tests.json (or "all")' % (i, it.get('test')))
        action = get(it, 'response', 'action')
        if it.get('category') in FACT_CATEGORIES and action == 'open':
            P.append('[CRITIQUE-FACT] critique.json: items[%d] reports a %s and remains open: fix it or reject it with a '
                     'reason (factual and arithmetic errors stop the run)' % (i, it.get('category')))
        elif it.get('severity') == 'blocking' and action == 'open':
            W.append('mark: [CRITIQUE] critique.json: items[%d] has critic severity blocking and remains open; '
                     'the host may answer it or leave it open' % i)
        if action in ('fixed', 'rejected') and not text(get(it, 'response', 'note')):
            P.append('[CRITIQUE] critique.json: items[%d].response.note must say what was done or why it was rejected' % i)
        if corpus is not None and text(it.get('text')) and norm(it.get('text')) not in corpus:
            P.append('[CRITIQUE] critique.json: items[%d].text is not in the critic\'s raw answer %s: copy the critic\'s '
                     'words' % (i, d.get('raw_output')))
    tv = d.get('trap_verdicts')
    if not isinstance(tv, dict):
        P.append('[CRITIQUE] critique.json: trap_verdicts (a verdict of the critic per test and per trap) is required')
        return
    allowed = TRAP_VERDICTS + (('not_returned',) if d.get('route') == 'vp-contradictor' else ())
    for tid in test_ids:
        per = tv.get(tid)
        if not isinstance(per, dict):
            P.append('[CRITIQUE] critique.json: trap_verdicts.%s is missing' % tid)
            continue
        for trap in TRAPS:
            v = per.get(trap)
            if not isinstance(v, dict):
                P.append('[CRITIQUE] critique.json: trap_verdicts.%s.%s is missing' % (tid, trap))
                continue
            if v.get('verdict') not in allowed:
                P.append('[CRITIQUE] critique.json: trap_verdicts.%s.%s.verdict must be one of %s'
                         % (tid, trap, ', '.join(allowed)))
            if not text(v.get('why')):
                P.append('[CRITIQUE] critique.json: trap_verdicts.%s.%s.why is empty' % (tid, trap))
            elif v.get('verdict') != 'not_returned' and corpus is not None and norm(v.get('why')) not in corpus:
                P.append('[CRITIQUE] critique.json: trap_verdicts.%s.%s.why is not in the critic\'s raw answer'
                         % (tid, trap))
            if v.get('verdict') == 'not_addressed' and not any(
                    isinstance(it, dict) and it.get('category') == 'trap_unaddressed' and it.get('test') == tid
                    for it in items):
                P.append('[CRITIQUE] critique.json: the critic finds trap %s of %s not addressed: an item '
                         '"trap_unaddressed" on %s is required (with its response)' % (trap, tid, tid))


# ---------------------------------------------------------------- result, proof, recommendation, log


def check_result(d, test_ids, P):
    if not isinstance(d, dict):
        return
    if d.get('mode') == 'plan only':
        if not text(d.get('reason')):
            P.append('[RESULT] result.json: plan only needs its reason')
        return
    if d.get('mode') == 'executed':
        if d.get('test') not in test_ids:
            P.append('[RESULT] result.json: executed test %r is not in tests.json' % d.get('test'))
        if not isinstance(d.get('execution'), dict):
            P.append('[RESULT] result.json: executed without an execution record (tools/run_test.py writes it)')
        if not text(d.get('observed')):
            P.append('[RESULT] result.json: "observed" is empty: write what the test showed')
        if d.get('decision') not in DECISIONS:
            P.append('[RESULT] result.json: decision must be one of %s, applied from the rule fixed before'
                     % ', '.join(DECISIONS))


def check_proof(work, result, tests_json, P):
    if not isinstance(result, dict) or result.get('mode') != 'executed':
        return
    tid = result.get('test')
    bf = result.get('before_fingerprint')
    if not isinstance(bf, str) or not re.fullmatch(r'[0-9a-f]{64}', bf):
        P.append('[PROOF] result.json: an executed result needs before_fingerprint (written by tools/run_test.py from '
                 'the "before" of %s)' % tid)
        return
    t = common.find_test(tests_json, tid)
    if t is not None and common.fingerprint(t) != bf:
        P.append('[PROOF] result.json: the protocol of %s in tests.json no longer has the fingerprint executed; the '
                 'predictions, rule or simulation changed after the execution' % tid)
    entries, _ = read_log(work)
    started = parse_utc(get(result, 'execution', 'started_utc'))
    ok = [e for e in entries or [] if e.get('phase') == 'before' and e.get('test') == tid and e.get('fingerprint') == bf
          and parse_utc(e.get('utc')) and started and parse_utc(e.get('utc')) <= started]
    if not ok:
        P.append('[PROOF] result.json: no "before" of %s with fingerprint %s... written before the execution started'
                 % (tid, bf[:12]))


def check_reco(d, P):
    if not isinstance(d, dict):
        return
    reason = d.get('reason')
    if len(sentences(reason)) != 1:
        P.append('[RECO] recommendation.json: the reason must be one sentence')
    if CERTIFY.search(text(reason)):
        P.append('[RECO] recommendation.json: the reason must not certify novelty or value (%r)'
                 % CERTIFY.search(text(reason)).group(0))


def read_log(work):
    """(entries, problems) of decision_log.jsonl; entries are the valid lines in order."""
    p = work / LOG
    if not p.exists():
        return None, []
    schema = read_json(SCHEMAS / 'decision_log_entry.json')
    entries, probs = [], []
    for n, line in enumerate(p.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except ValueError:
            probs.append('[LOG] %s: line %d is not JSON' % (LOG, n))
            continue
        errs = schema_lite.validate(e, schema)
        if errs:
            probs.append('[LOG] %s: line %d: %s' % (LOG, n, '; '.join(errs)))
            continue
        entries.append(e)
    return entries, probs


def check_log(work, result, P):
    entries, probs = read_log(work)
    if entries is None:
        P.append('[LOG] %s: required, with at least one "before" entry written by tools/log.py' % LOG)
        return
    P.extend(probs)
    befores = {}
    for e in entries:
        if e['phase'] == 'before':
            befores.setdefault(e['test'], e)
        elif e['test'] not in befores:
            P.append('[LOG] %s: "after" for %s without a "before"' % (LOG, e['test']))
    if not befores:
        P.append('[LOG] %s: no "before" entry (what the researcher would do before the result)' % LOG)
    if isinstance(result, dict) and result.get('mode') == 'executed':
        tid = result.get('test')
        b = befores.get(tid)
        started = parse_utc(get(result, 'execution', 'started_utc'))
        if b is None:
            P.append('[LOG] %s: test %s was executed without a "before" entry' % (LOG, tid))
        elif started and parse_utc(b['utc']) and parse_utc(b['utc']) > started:
            P.append('[LOG] %s: the "before" of %s (%s) was written after the execution started' % (LOG, tid, b['utc']))


# ---------------------------------------------------------------- run.json: form and budget


def check_run_json(work, data, P):
    p = work / RUN
    if not p.exists():
        P.append('[RUNLOG] %s: required (tools/step.py writes one entry per step, with its cost and duration)' % RUN)
        return
    try:
        rj = read_json(p)
    except (ValueError, UnicodeDecodeError) as e:
        P.append('[RUNLOG] %s: %s' % (RUN, e))
        return
    errs = schema_lite.validate(rj, read_json(SCHEMAS / RUN))
    for e in errs:
        P.append('[RUNLOG] %s: %s' % (RUN, e))
    if errs:
        return
    steps = rj['steps']
    for i, s in enumerate(steps):
        for k in ('duration_s', 'cost_usd'):
            v = s.get(k)
            if not ((is_num(v) and v >= 0) or v == 'unknown'):
                P.append('[RUNLOG] %s: steps[%d].%s must be a number >= 0 or "unknown" (found %r)' % (RUN, i, k, v))
    budget = common.config()['budget']
    count = {}
    for s in steps:
        count[s['step']] = count.get(s['step'], 0) + 1
    budget = dict(budget, second_critiques=common.config()['second_critiques_max'],
                  rebound_critiques=common.config().get('rebound_critiques_max', 0))      # Extra critique budgets are separate from the protocol budget.
    for step, key in (('vp_run', 'vp_runs'), ('critique', 'critiques'), ('critique2', 'second_critiques'),
                      ('execution', 'executions'), ('rebound_critique', 'rebound_critiques')):
        if count.get(step, 0) > budget.get(key, 0):
            location = ('rebound_critiques_max' if step == 'rebound_critique' else
                        'second_critiques_max' if step == 'critique2' else 'budget.' + key)
            P.append('[BUDGET] %s: %d "%s" steps, more than the budget per idea (%d, config.json %s)'
                     % (RUN, count[step], step, budget.get(key, 0), location))
    runs = get(data.get('intake.json'), 'vp', 'runs')
    rb_cap = common.config()['rebound']['prior_art_checks_card_max']
    if count.get('rebound_vp_run', 0) > rb_cap:
        P.append('[BUDGET] %s: %d "rebound_vp_run" steps, more than the budget per card (%d, config.json '
                 'rebound.prior_art_checks_card_max)' % (RUN, count['rebound_vp_run'], rb_cap))
    named = {s.get('vp_run') for s in steps if s['step'] in ('vp_run', 'rebound_vp_run')}
    if vp_mode(data) == 'vp' and isinstance(runs, dict):
        for name in runs:
            if name not in named:
                P.append('[BUDGET] %s: VP run %r of intake.json has no "vp_run" step (tools/step.py --step vp_run '
                         '--vp-run %s)' % (RUN, name, name))
    if isinstance(data.get('critique.json'), dict) and not count.get('critique'):
        P.append('[BUDGET] %s: critique.json exists but no "critique" step is recorded' % RUN)
    rb = data.get('rebound.json')
    if isinstance(rb, dict) and ('idea_critique' in rb or any(
            isinstance(i, dict) and 'critique' in i for i in rb.get('ideas') or [])) \
            and not count.get('rebound_critique'):
        P.append('[BUDGET] %s: rebound.json has a recorded critique but no "rebound_critique" step is recorded '
                 '(tools/step.py --step rebound_critique)' % RUN)
    res = data.get('result.json')
    if isinstance(res, dict) and res.get('mode') == 'executed' and not count.get('execution'):
        P.append('[BUDGET] %s: the result is executed but no "execution" step is recorded (tools/run_test.py writes it)'
                 % RUN)


# ---------------------------------------------------------------- references


def iter_refs(data):
    """(where, ref, year of the enclosing work or None) for every reference of prior_art.json and hypotheses.json."""
    pa = data.get('prior_art.json')
    if isinstance(pa, dict):
        for i, c in enumerate(pa.get('closest_work') or []):
            if isinstance(c, dict) and isinstance(c.get('ref'), dict):
                yield 'prior_art.json closest_work[%d]' % i, c['ref'], c.get('year')
        mats = pa.get('materials') if isinstance(pa.get('materials'), dict) else {}
        for key, items in mats.items():
            for i, m in enumerate(items if isinstance(items, list) else []):
                for j, r in enumerate((m.get('refs') or []) if isinstance(m, dict) else []):
                    if isinstance(r, dict):
                        yield 'prior_art.json materials.%s[%d].refs[%d]' % (key, i, j), r, None
    hy = data.get('hypotheses.json')
    if isinstance(hy, dict):
        for group in ('hypotheses', 'rivals'):
            for h in hy.get(group) or []:
                if not isinstance(h, dict):
                    continue
                for side in ('for', 'against'):
                    for j, r in enumerate(h.get(side) or []):
                        if isinstance(r, dict):
                            yield 'hypotheses.json %s.%s[%d]' % (h.get('id'), side, j), r, None
    ev = data.get('evidence_table.json')
    for i, e in enumerate((ev.get('entries') if isinstance(ev, dict) else None) or []):
        if isinstance(e, dict) and isinstance(e.get('source'), dict):
            yield 'evidence_table.json %s source' % e.get('id', i), e['source'], None
    for fname in REBOUND_FILES:
        rb = data.get(fname)
        for idea in (rb.get('ideas') if isinstance(rb, dict) else None) or []:
            if not isinstance(idea, dict):
                continue
            tag = '%s %s' % (fname, idea.get('id'))
            for j, m in enumerate(idea.get('materials') or []):
                if isinstance(m, dict) and isinstance(m.get('ref'), dict):
                    yield '%s materials[%d]' % (tag, j), m['ref'], None
            pa = idea.get('prior_art')
            for j, c in enumerate((pa.get('closest_work') if isinstance(pa, dict) else None) or []):
                if isinstance(c, dict) and isinstance(c.get('ref'), dict):
                    yield '%s closest_work[%d]' % (tag, j), c['ref'], c.get('year')
            fe = idea.get('feasibility')
            for el, v in (fe.items() if isinstance(fe, dict) else []):
                if isinstance(v, dict) and isinstance(v.get('ref'), dict):
                    yield '%s feasibility.%s' % (tag, el), v['ref'], None


def _norm_id(s):
    s = text(s).lower()
    s = re.sub(r'^doi:\s*(https?://(dx\.)?doi\.org/)?', 'doi:', s)
    return s


def _source_ids(src):
    out = set()
    for k, v in (src or {}).items():
        if k in NON_ID_FIELDS or not isinstance(v, str):
            continue
        out.add(_norm_id('%s:%s' % (k, v)))
        out.add(_norm_id(v))
    return out


class VPRuns:
    """Lazy reader of the VP runs named in intake.json: verdicts.json, card.json, state/journal.jsonl, and the years of
    STUDIES.json / result.json (real VP formats: a verdict's "source" is the key string "S<n>")."""

    def __init__(self, work, intake):
        self.work = work
        self.runs = get(intake, 'vp', 'runs') or {}
        self.cache = {}

    def run(self, name):
        if name in self.cache:
            return self.cache[name]
        info = {'dir': None, 'verdicts': None, 'card': None, 'card_claims': {}, 'journal': None, 'journal_error': None,
                'years': {}, 'error': None}
        path = self.runs.get(name) if isinstance(self.runs, dict) else None
        if not isinstance(path, str):
            info['error'] = 'VP run %r is not listed in intake.json vp.runs' % name
            self.cache[name] = info
            return info
        d = Path(path)
        d = d if d.is_absolute() else (self.work / d)
        info['dir'] = d
        try:
            v = read_json(d / 'verdicts.json')
            info['verdicts'] = {c.get('id'): c.get('status') for c in v.get('claims', []) if isinstance(c, dict)}
        except (OSError, ValueError, AttributeError):
            info['error'] = 'no readable verdicts.json in VP run %r (%s)' % (name, d)
        try:
            card = read_json(d / 'card.json')
            if isinstance(card, dict):
                info['card'] = card
                for c in card.get('claims', []):
                    if isinstance(c, dict):
                        src = (card.get('sources') or {}).get(get(c, 'source', 'key')) or {}
                        info['card_claims'][c.get('id')] = src
        except (OSError, ValueError):
            pass
        jp = d / 'state' / 'journal.jsonl'
        try:
            lines = [l for l in jp.read_text(encoding='utf-8').splitlines() if l.strip()]
            entries = [json.loads(l) for l in lines]
            if not entries or not all(isinstance(e, dict) for e in entries):
                info['journal_error'] = 'empty'
            elif not any(e.get('call') for e in entries):
                info['journal_error'] = 'no gateway call recorded'
            else:
                info['journal'] = entries
        except OSError:
            info['journal_error'] = 'missing'
        except ValueError:
            info['journal_error'] = 'not JSON lines'
        for fname in ('STUDIES.json', 'result.json'):
            try:
                st = read_json(d / fname)
            except (OSError, ValueError):
                continue
            items = st.get('studies') if isinstance(st, dict) else st
            for s in items if isinstance(items, list) else []:
                if not isinstance(s, dict) or year_of(s.get('year')) is None:
                    continue
                ids = {_norm_id(s.get('id'))} if text(s.get('id')) else set()
                for k in ('doi', 'pmid', 'arxiv'):
                    if text(s.get(k)):
                        ids.add(_norm_id('%s:%s' % (k, s[k])))
                for i in ids:
                    info['years'].setdefault(i, year_of(s.get('year')))
        self.cache[name] = info
        return info


def ref_check(vp, ref):
    """(status or None, problem code or None, message)."""
    run_name, claim = ref.get('run'), ref.get('claim')
    if not run_name or not claim:
        return None, '[REF-MISSING]', 'with VP every reference names its VP run and claim id ("run", "claim")'
    info = vp.run(run_name)
    if info['error']:
        return None, '[REF-MISSING]', info['error']
    if info['card'] is None:
        return None, '[REF-CARD]', 'VP run %r has no readable card.json (%s): the reference cannot be checked' % (
            run_name, info['dir'])
    status = info['verdicts'].get(claim)
    if status is None:
        return None, '[REF-MISSING]', 'claim %s has no verdict in %s/verdicts.json' % (claim, info['dir'])
    if claim not in info['card_claims']:
        return status, '[VP-RUN]', 'claim %s is not in %s/card.json' % (claim, info['dir'])
    if status == 'ABSENT':
        return status, '[REF-ABSENT]', 'claim %s is ABSENT in the VP verification: remove the reference' % claim
    if status == 'INVALID':
        return status, '[REF-INVALID]', 'claim %s is INVALID in the VP verification: remove the reference' % claim
    if status not in OK_STATUSES:
        return status, '[REF-MISSING]', 'claim %s has an unknown status %r' % (claim, status)
    if _norm_id(ref.get('id')) not in _source_ids(info['card_claims'][claim]):
        return status, '[REF-MISMATCH]', 'identifier %s is not the source of claim %s in %s/card.json' % (
            ref.get('id'), claim, info['dir'])
    return status, None, ''


def ref_years(vp, ref, container_year):
    """Years known for a reference: its own, its enclosing work's, card.json's and STUDIES.json / result.json's."""
    years = [year_of(ref.get('year')), year_of(container_year)]
    if vp is not None and ref.get('run'):
        info = vp.run(ref.get('run'))
        src = info['card_claims'].get(ref.get('claim')) or {}
        years.append(year_of(src.get('year')))
        for i in {_norm_id(ref.get('id'))} | _source_ids(src):
            years.append(info['years'].get(i))
    return [y for y in years if y is not None]


def check_refs(work, data, P):
    intake = data.get('intake.json')
    t_year = intake_year(data)
    vp = VPRuns(work, intake) if vp_mode(data) == 'vp' else None
    if vp is not None:
        T = text(get(intake, 'T'))
        for name in sorted(vp.runs) if isinstance(vp.runs, dict) else []:
            info = vp.run(name)
            if info['dir'] is None:
                continue
            if info['journal_error']:
                P.append('[VP-RUN] intake.json vp.runs.%s: %s/state/journal.jsonl (the VP gateway journal) is %s: not a '
                         'VP run' % (name, info['dir'], info['journal_error']))
            elif any(e.get('call') and not text(e.get('T')) for e in info['journal']):
                P.append('[DATE] intake.json vp.runs.%s: a VP gateway call without T in %s/state/journal.jsonl: the date '
                         'barrier cannot be checked' % (name, info['dir']))
            elif T:
                late = sorted({e.get('T') for e in info['journal'] if text(e.get('T')) and e.get('T') > T})
                if late:
                    P.append('[DATE] intake.json vp.runs.%s: the VP gateway ran with T %s, after the T of the idea (%s): '
                             'pass --T %s to VP' % (name, ', '.join(late), T, T))
            if info['card'] is None and not info['error']:
                P.append('[REF-CARD] intake.json vp.runs.%s: %s/card.json is missing: VP references cannot be checked'
                         % (name, info['dir']))
    for where, ref, cy in iter_refs(data):
        if vp is not None:
            status, code, msg = ref_check(vp, ref)
            if code:
                P.append('%s %s: %s: %s' % (code, where, ref.get('id'), msg))
        if t_year is not None:
            late = [y for y in ref_years(vp, ref, cy) if y > t_year]
            if late:
                P.append('[DATE] %s: %s is dated %d, after T (%s): nothing published after T is used'
                         % (where, ref.get('id'), max(late), get(intake, 'T')))


def reference_statuses(work):
    work = Path(work)
    data, _ = load(work)
    out = {}
    if vp_mode(data) != 'vp':
        return out
    vp = VPRuns(work, data.get('intake.json'))
    for _, ref, _ in iter_refs(data):
        status, _, _ = ref_check(vp, ref)
        if status is None:
            continue
        rid = ref.get('id')
        if rid not in out or STATUS_RANK.get(status, 9) > STATUS_RANK.get(out[rid], 9):
            out[rid] = status
    return out


def unverified_references(work):
    out = {rid: st for rid, st in reference_statuses(work).items() if st in UNVERIFIED_STATUSES}
    work = Path(work)
    data, _ = load(work)
    if vp_mode(data) == 'vp':                   # a DISTORTED reference of a rebound file is listed too (round 2, RB44)
        vp = VPRuns(work, data.get('intake.json'))
        for where, ref, _ in iter_refs(data):
            if where.startswith(tuple(REBOUND_FILES)) and ref_check(vp, ref)[0] == 'DISTORTED':
                out.setdefault(ref.get('id'), 'DISTORTED')
    return sorted(out.items())


def ref_status(work, ref):
    """Status of one reference (dict) of the working directory, or None without VP."""
    work = Path(work)
    data, _ = load(work)
    if vp_mode(data) != 'vp':
        return None
    status, _, _ = ref_check(VPRuns(work, data.get('intake.json')), ref)
    return status


# ---------------------------------------------------------------- card


def inputs_fingerprint(work):
    """SHA-256 over the files the card is assembled from (name and bytes, in a fixed order)."""
    h = hashlib.sha256()
    # the rebound files count only when present: a directory without them keeps the fingerprint of the round before
    for name in CARD_INPUTS + [n for n in REBOUND_FILES + ['history.json'] + NEW_INPUTS if (Path(work) / n).exists()]:
        p = Path(work) / name
        h.update(name.encode('utf-8') + b'\0')
        h.update(p.read_bytes() if p.exists() else b'<absent>')
        h.update(b'\0')
    # Opt-in V4 artifacts bind the current derivation too, so editing a source
    # journal cannot leave a saved ledger/card looking current. Legacy hashes
    # keep their previous definition when neither artifact is present.
    if any((Path(work) / n).exists() for n in ('test_revision.json', 'overlap_ledger.json')):
        import overlap
        h.update(json.dumps(overlap.derive(work), sort_keys=True, ensure_ascii=False).encode('utf-8'))
    return h.hexdigest()


def card_text_problems(work, card_text, mode=None):
    work = Path(work)
    if mode is None:
        data, _ = load(work)
        mode = vp_mode(data)
    P = []
    lines = card_text.splitlines()
    content = [line for line in lines if line.strip()]
    intake = _json_or_none(work / 'intake.json')
    expected = disclaimer.get_disclaimer(intake.get('language') if isinstance(intake, dict) else None)
    if not lines or lines[0] != expected:
        P.append('[DISCLAIMER] %s: the first physical line must be %r' % (CARD, expected))
    if mode != 'vp' and (len(content) < 2 or content[1].strip() != HEADER):
        P.append('[HEADER] %s: without VP the line immediately after the disclaimer must be %r' % (CARD, HEADER))
    cap = common.config().get('card_max_lines', 80) if guards.is_v2(work) else CARD_MAX_LINES
    if len(lines) > cap:
        P.append('[CARD] %s: %d lines, more than one page (%d)' % (CARD, len(lines), cap))
    if guards.is_r3(work):                    # round 3 (2.1): the card never cuts a text; a mark the inputs do not hold is a cut
        src = '\n'.join(s for n in CARD_INPUTS + ['decisive_claims.json', 'framing.json', 'research_plan.json', 'named_elements.json'] if (work / n).is_file()
                        for s in r3check.strings(_json_or_none(work / n) if n.endswith('.json') else (work / n).read_text(encoding='utf-8')))
        for mark in r3check.card_truncation(card_text):
            if card_text.count(mark) > src.count(mark):
                P.append('[CARD-TRUNC] %s: the card holds %r that its input files do not: a text was cut (the R3 card shortens '
                         'only by whole sentences, and points to %s)' % (CARD, mark, REPORT))
    if any(line.startswith('Tournament [TOURNOI]:') for line in lines):
        P.append('[CARD-STALE] %s: obsolete [TOURNOI] output mark: run tools/card.py again' % CARD)
    m = CARD_FP.search(card_text)
    if not m or m.group(1) != inputs_fingerprint(work):
        P.append('[CARD-STALE] %s: the card does not match the current files (an entry was added or a file changed '
                 'after it was assembled): run tools/card.py again' % CARD)
    return P


def _json_or_none(p):
    try:
        return read_json(p)
    except (OSError, ValueError):
        return None


def check_card(work, mode, P):
    p = work / CARD
    if p.exists():
        P.extend(card_text_problems(work, p.read_text(encoding='utf-8'), mode))


# ---------------------------------------------------------------- rebound (steps 8 and 8-bis)

REB_STRUCT_MIN = 12          # a filled text field of an idea: at least 12 characters, and no placeholder
FOLLOW_UP = {'refuted': ('competing_explanation', 'repairable_variant'),
             'confirmed': ('scope_extension', 'transfer'),
             'indeterminate': ('competing_explanation', 'repairable_variant')}
RESULT_OUTCOME = {'continue': 'confirmed', 'stop': 'refuted', 'revise': 'refuted', 'indeterminate': 'indeterminate'}
SCORE_KEY = re.compile(r'novel|origin|score|rating|grade|interest|promis', re.I)
SCORE_TEXT = re.compile(
    r'\b(novelty|originality|novel|original|interest(?:ingness)?|promise)\b[^.\n]{0,40}?\d+(?:[.,]\d+)?\s*'
    r'(?:/\s*\d+|out of\s*\d+|points?\b|%|stars?\b)'
    r'|\b\d+(?:[.,]\d+)?\s*(?:/\s*(?:5|10|100)\b|out of\s*(?:5|10|100)\b)', re.I)
REB_TEXT_SKIP = ('ref', 'refs', 'queries', 'says')


def filled(x, n=REB_STRUCT_MIN):
    return isinstance(x, str) and not common.is_placeholder(x, n)


def _walk_numbers(x, path, allowed):
    """Paths of the numbers found under x, except those where allowed(path_tuple) is true."""
    out = []
    if isinstance(x, bool):
        return out
    if isinstance(x, (int, float)):
        return [] if allowed(path) else ['.'.join(map(str, path))]
    if isinstance(x, dict):
        for k, v in x.items():
            out += _walk_numbers(v, path + (k,), allowed)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            out += _walk_numbers(v, path + (i,), allowed)
    return out


def _texts(x, skip=REB_TEXT_SKIP, parent=None):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            if k in skip or (k == 'title' and parent == 'closest_work'):
                continue
            for s in _texts(v, skip, k):
                yield s
    elif isinstance(x, list):
        for v in x:
            for s in _texts(v, skip, parent):
                yield s


def _is_amount(path):
    return ((len(path) >= 3 and path[-1] == 'amount' and path[-3:-2] == ('feasibility',))
            or (len(path) == 3 and path[:2] == ('repair', 'critique_items')))
    # Critique item indices are audit links, not idea scores; their values are
    # validated separately by rebound and the schema.


def novelty_problems(tag, obj, allow_amount, P):
    """[REB-NOVELTY]: no numeric note of novelty, no number outside feasibility amounts, no certification wording."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if SCORE_KEY.search(str(k)) and not isinstance(v, (dict, list, str)) and v is not None:
                P.append('[REB-NOVELTY] %s: field %r holds a value: a neighbouring idea carries no numeric note of novelty, '
                         'interest or promise' % (tag, k))
    for p in _walk_numbers(obj, (), _is_amount if allow_amount else (lambda path: False)):
        P.append('[REB-NOVELTY] %s: a number at %s: the only number of an idea is feasibility.<element>.amount; no score, '
                 'rating or rank' % (tag, p))
    for s in _texts(obj):
        m = SCORE_TEXT.search(s)
        if m:
            P.append('[REB-NOVELTY] %s: %r reads as a numeric note; neighbouring ideas are not scored' % (tag, m.group(0)))
        c = CERTIFY.search(s)
        if c:
            P.append('[REB-NOVELTY] %s: %r certifies novelty or value; "Not found" is never "new"' % (tag, c.group(0)))


ORDER_TEXT = re.compile(
    r'\brank(?:ed|ing)?\s+(?:first|second|third|1st|2nd|3rd|\d+)\b|\b(?:top|first|highest)[- ]ranked\b'
    r'|\branked\s+(?:first|top|highest)\b|\bbest\s+(?:idea|option|choice|candidate)\b|\btop\s+(?:idea|pick|choice|candidate)\b'
    r'|\bmost\s+promising\b|\bnumber\s+one\b|\bno\.?\s*1\b|#\s?1\b|\bfirst\s+(?:priority|choice|pick)\b'
    r'|\bhighest\s+priority\b|\bshould\s+(?:come|be\s+done)\s+first\b|\b(?:1st|2nd|3rd)\b', re.I)


def order_wording_problems(tag, obj, P):
    """[REB-ORDER]: no ordinal wording that ranks ideas in disguise. A lexical net: it cannot prove that no order is implied."""
    for s in _texts(obj):
        m = ORDER_TEXT.search(s)
        if m:
            P.append('[REB-ORDER] %s: %r orders the ideas; no order is imposed, the researcher orders or rejects' % (tag, m.group(0)))


def _vp_prior_art_answer(vp, run_name):
    """(answer or None, problem text or None) of the PRIOR-ART.md of a VP run."""
    info = vp.run(run_name)
    if info['dir'] is None:
        return None, 'VP run %r is not listed in intake.json vp.runs' % run_name
    try:
        md = (info['dir'] / 'PRIOR-ART.md').read_text(encoding='utf-8')
    except OSError:
        return None, '%s/PRIOR-ART.md cannot be read' % info['dir']
    m = PRIOR_ART_LINE.search(md)
    return (PRIOR_ART_ANSWERS.get(m.group(1).strip()) if m else None), None


def check_rb_prior_art(tag, idea, mode, vp, P, W, ranked=None):
    pa = idea.get('prior_art')
    if not isinstance(pa, dict):
        P.append('[REB-PRIOR-ART] %s: no prior-art check: every neighbouring idea is checked (never skipped, never '
                 'pre-sorted by the model)' % tag)
        return
    status = pa.get('status')
    unc = pa.get('uncontrolled') is True
    closest = pa.get('closest_work') if isinstance(pa.get('closest_work'), list) else []
    if unc:
        if status != 'Insufficient search':
            P.append('[REB-PRIOR-ART] %s: an idea not checked for lack of budget has the status "Insufficient search"' % tag)
        return
    if not [q for q in pa.get('queries') or [] if isinstance(q, str) and q.strip()]:
        P.append('[REB-PRIOR-ART] %s: the queries of the check are not written' % tag)
    if not filled(pa.get('scope'), 10):
        P.append('[REB-PRIOR-ART] %s: the scope of the check (sources, dates, fields) is not written' % tag)
    if status in ('Exists', 'Partially'):
        if not closest:
            P.append('[REB-PRIOR-ART] %s: status %r needs at least one closest work' % (tag, status))
        if status == 'Partially' and not filled(pa.get('difference'), 10):
            P.append('[REB-PRIOR-ART] %s: "Partially" shows the exact difference with the closest work ("difference")' % tag)
    for j, c in enumerate(closest):
        if isinstance(c, dict) and (not text(c.get('what_differs')) or not text(c.get('title'))
                                    or not isinstance(c.get('ref'), dict)):
            P.append('[REB-PRIOR-ART] %s: closest_work[%d] needs ref, title and what_differs' % (tag, j))
    if pa.get('recognised_by_model_only') is True:
        W.append('[REB-PRIOR-ART] %s: recognised by the model without a verified source: shown as unverified' % tag)
    if mode == 'vp' and vp is not None:
        run = pa.get('vp_run')
        if not text(run):
            P.append('[REB-PRIOR-ART] %s: with VP, the check is a VP run (vp_run, listed in intake.json vp.runs)' % tag)
            return
        answer, why = _vp_prior_art_answer(vp, run)
        if why:
            P.append('[REB-PRIOR-ART] %s: %s' % (tag, why))
        elif status == 'Insufficient search':
            pass                                  # lowering the answer is allowed, raising it never
        elif answer is None:
            P.append('[REB-PRIOR-ART] %s: the PRIOR-ART.md of run %s has no answer line: the status is "Insufficient search"'
                     % (tag, run))
        elif answer != status:
            P.append('[REB-PRIOR-ART] %s: status %r differs from the answer %r of VP run %s; copy it, never upgrade or '
                     'soften it' % (tag, status, answer, run))
        check_rb_journal(tag, pa, run, vp, ranked, P)
        for j, c in enumerate(closest):
            ref = c.get('ref') if isinstance(c, dict) else None
            if isinstance(ref, dict) and ref.get('run') != run:
                P.append('[REB-PRIOR-ART] %s: closest_work[%d] cites VP run %r but the check of this idea is VP run %r: the '
                         'closest work comes from the idea\'s own VP run' % (tag, j, ref.get('run'), run))
    else:
        W.append('[REB-PRIOR-ART] %s: not verified: no VP (the search is the host\'s own, its queries are written but not '
                 'checked against a gateway journal)' % tag)


def _norm_query(q):
    return ' '.join(q.lower().split())


def _journal_time(s):
    """Naive UTC datetime of a gateway journal 'utc' (ISO 8601, with or without offset), or None."""
    try:
        dt = datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt


def check_rb_journal(tag, pa, run, vp, ranked, P):
    """The written queries of an idea are queries of the gateway journal of its own VP run, sent no later than the declared
    date, itself no later than the ranking (the search is registered, not just declared)."""
    info = vp.run(run)
    if info['dir'] is None:
        return                                    # reported by _vp_prior_art_answer
    entries = info['journal']
    if entries is None:
        P.append('[REB-PRIOR-ART] %s: VP run %s has no readable gateway journal (state/journal.jsonl: %s): the search '
                 'cannot be registered' % (tag, run, info['journal_error']))
        return
    searches = [e for e in entries if str(e.get('call')).startswith('search') and isinstance(e.get('query'), str)]
    if not searches:
        P.append('[REB-PRIOR-ART] %s: the gateway journal of VP run %s holds no search call' % (tag, run))
        return
    by_query = {}
    for e in searches:
        by_query.setdefault(_norm_query(e['query']), []).append(e)
    date = parse_utc(pa.get('date'))
    rk = parse_utc(ranked) if ranked else None
    for q in pa.get('queries') or []:
        if not isinstance(q, str) or not q.strip():
            continue
        hits = by_query.get(_norm_query(q))
        if not hits:
            P.append('[REB-PRIOR-ART] %s: query %r is not in the gateway journal of VP run %s (state/journal.jsonl): every '
                     'written query was sent through the gateway' % (tag, q, run))
            continue
        for e in hits:
            t = _journal_time(e.get('utc'))
            if t is None:
                P.append('[REB-PRIOR-ART] %s: a gateway call of VP run %s has no readable utc' % (tag, run))
                break
            if date is not None and t > date:
                P.append('[REB-PRIOR-ART] %s: query %r was sent at %s, after the date of the check (%s)'
                         % (tag, q, e.get('utc'), pa.get('date')))
                break
            if rk is not None and t > rk:
                P.append('[REB-ORDER] %s: query %r was sent at %s, after the ranking (%s): the check precedes any ranking'
                         % (tag, q, e.get('utc'), ranked))
                break


def check_rb_feasibility(tag, idea, P):
    fe = idea.get('feasibility')
    if not isinstance(fe, dict):
        return
    for el in ('data', 'tool', 'time', 'compute'):
        v = fe.get(el)
        if not isinstance(v, dict) or v.get('status') != 'established':
            continue
        if el in ('data', 'tool'):
            for f in ('name', 'access'):
                if not filled(v.get(f), 4):
                    P.append('[REB-FEAS] %s: feasibility.%s is "established" without a named %s (a named, reachable %s; '
                             'else "not established")' % (tag, el, f, 'dataset' if el == 'data' else 'tool'))
        else:
            if not is_num(v.get('amount')) or v['amount'] < 0 or not filled(v.get('unit'), 2):
                P.append('[REB-FEAS] %s: feasibility.%s is "established" without a number (amount) and its unit; else '
                         '"not established"' % (tag, el))


def check_rb_idea(fname, idea, files, mode, vp, P, W, ranked=None):
    iid = idea.get('id')
    tag = '%s %s' % (fname, iid)
    op = idea.get('operator')
    if op not in rebound.OPERATORS:
        P.append('[REB-OPERATOR] %s: operator %r is not one of %s' % (tag, op, ', '.join(rebound.OPERATORS)))
    if not isinstance(idea.get('recurring_ingredient'), bool):
        P.append('[REB-OPERATOR] %s: recurring_ingredient must be true or false' % tag)
    elif idea['recurring_ingredient'] and op in rebound.OPERATORS and op not in rebound.MEASURABLE:
        P.append('[REB-OPERATOR] %s: operator %s is "not measured" (no source found): recurring_ingredient must be false'
                 % (tag, op))
    if op == 'analogy':
        an = idea.get('analogy')
        if not isinstance(an, dict) or not filled(an.get('corresponds'), 10) or not filled(an.get('breaks'), 10):
            P.append('[REB-OPERATOR] %s: an analogy says what corresponds and what breaks between the two domains '
                     '(analogy.corresponds, analogy.breaks)' % tag)
    if op == 'literature_bridge':
        br = idea.get('bridge')
        if not isinstance(br, dict) or not filled(br.get('intermediate_concept'), 4) or not filled(br.get('neighbouring_field'), 4):
            P.append('[REB-OPERATOR] %s: a literature bridge names its intermediate concept and the neighbouring field '
                     '(bridge)' % tag)
    mats = idea.get('materials') if isinstance(idea.get('materials'), list) else []
    if not mats:
        P.append('[REB-MATERIAL] %s: no material: every idea comes from at least one cited reference or entry of '
                 'prior_art.json / hypotheses.json' % tag)
    anomaly_ok = False
    for j, m in enumerate(mats):
        if not isinstance(m, dict):
            continue
        if m.get('kind') == 'reference':
            if not isinstance(m.get('ref'), dict) or not text(m['ref'].get('id')):
                P.append('[REB-MATERIAL] %s: materials[%d] is a reference without ref.id' % (tag, j))
            anomaly_ok = True
        elif m.get('kind') == 'entry':
            if not rebound.resolve_entry(m.get('entry'), files):
                P.append('[REB-MATERIAL] %s: materials[%d].entry %r does not name an existing entry (prior_art.json:'
                         'materials.<key>[i] or closest_work[i], hypotheses.json:<id>, tests.json:<id>, result.json:<id>)'
                         % (tag, j, m.get('entry')))
            elif re.match(r'prior_art\.json:materials\.(%s)\[' % '|'.join(rebound.ANOMALY_KEYS), m.get('entry')):
                anomaly_ok = True
        else:
            P.append('[REB-MATERIAL] %s: materials[%d].kind must be "reference" or "entry"' % (tag, j))
    if op == 'anomaly' and mats and not anomaly_ok:
        P.append('[REB-MATERIAL] %s: an anomaly idea cites an anomaly or contradiction (prior_art.json materials.'
                 'unexplained_anomalies / contradictory_results) or a reference' % tag)
    for blk, fields in (('mechanism', ('summary', 'goal')), ('hypothesis', ('statement', 'false_if')),
                        ('test', ('one_line', 'variable', 'if_holds', 'if_fails'))):
        b = idea.get(blk)
        if not isinstance(b, dict):
            continue
        for f in fields:
            if not filled(b.get(f)):
                P.append('[REB-STRUCT] %s: %s.%s is empty or a placeholder (at least %d characters)' % (tag, blk, f, REB_STRUCT_MIN))
    for f in ('title', 'statement', 'teaches'):
        if f in idea and not filled(idea.get(f), 3 if f == 'title' else REB_STRUCT_MIN):
            P.append('[REB-STRUCT] %s: %s is empty or a placeholder' % (tag, f))
    to = idea.get('tradeoffs')
    if isinstance(to, dict):
        for k in ('gains', 'costs', 'assumptions', 'uncertainties'):
            items = to.get(k)
            if not isinstance(items, list) or not items or not all(filled(x) for x in items):
                P.append('[REB-STRUCT] %s: tradeoffs.%s needs at least one written item (no placeholder)' % (tag, k))
    check_rb_prior_art(tag, idea, mode, vp, P, W, ranked)
    check_rb_feasibility(tag, idea, P)
    novelty_problems(tag, idea, True, P)
    order_wording_problems(tag, idea, P)


def check_rb_after(work, fname, d, data, ideas, P):
    test_ids = {t.get('id') for t in (get(data.get('tests.json'), 'tests') or []) if isinstance(t, dict)}
    at = d.get('after_test')
    if not text(at) or at not in test_ids:
        P.append('[REB-AFTER] %s: after_test %r is not a test of tests.json' % (fname, at))
    entries, _ = read_log(Path(work))
    scenario = d.get('outcome_source') == 'scenario'       # round 3 (2.3): a conditional continuation, no result behind it
    if not scenario and not any(e.get('phase') == 'after' and e.get('test') == at for e in entries or []):
        P.append('[REB-AFTER] %s: step 8-bis follows a result: decision_log.jsonl needs an "after" entry for %s '
                 '(tools/log.py)' % (fname, at))
    outcome = d.get('outcome')
    if outcome not in FOLLOW_UP:
        P.append('[REB-AFTER] %s: outcome must be refuted, confirmed or indeterminate' % fname)
    if d.get('outcome_source') not in ('result.json', 'researcher', 'assumption', 'scenario'):
        P.append('[REB-AFTER] %s: outcome_source must be result.json, researcher, scenario or assumption' % fname)
    if d.get('outcome_source') == 'assumption' and guards.is_r3(work):
        P.append('[REB-AFTER-ASSUMED] %s: the outcome of %s is an assumption: with no result behind it the continuations are '
                 'SCENARIOS (outcome_source "scenario", labelled on the card), never a "rebound after" a result' % (fname, at))
    res = data.get('result.json')
    if isinstance(res, dict) and res.get('mode') == 'executed' and res.get('test') == at and outcome in FOLLOW_UP and not scenario:
        want = RESULT_OUTCOME.get(res.get('decision'))
        if want and want != outcome:
            P.append('[REB-AFTER] %s: outcome %r but result.json decided %r for %s (continue = confirmed, stop and '
                     'revise = refuted, indeterminate = indeterminate)' % (fname, outcome, res.get('decision'), at))
    allowed = FOLLOW_UP.get(outcome, ())
    for idea in ideas:
        if idea.get('follow_up_kind') not in allowed:
            P.append('[REB-AFTER] %s %s: follow_up_kind %r does not fit the outcome %r (allowed: %s)'
                     % (fname, idea.get('id'), idea.get('follow_up_kind'), outcome, ', '.join(allowed)))


def _id_key(x):
    m = re.fullmatch(r'([A-Za-z]+)([0-9]+)', x)
    return (m.group(1), int(m.group(2)), x) if m else (x, 0, x)


def check_rb_file(work, fname, d, data, mode, vp, P, W):
    cfg = common.config()
    ideas = [i for i in d.get('ideas') or [] if isinstance(i, dict)] if isinstance(d.get('ideas'), list) else []
    stage = rebound.STAGE_OF[fname]
    if stage == '8':
        errors, marks = rebound.check_data(d, cfg)
        P.extend('[REB-REPAIR] %s: %s' % (fname, e) for e in errors)
        W.extend('mark: [REB-CRITIQUE] %s: %s' % (fname, m) for m in marks)
    if d.get('stage') != stage:
        P.append('[REB-STAGE] %s: stage must be %r in this file (found %r)' % (fname, stage, d.get('stage')))
    if stage == '8':
        extra = [k for k in ('after_test', 'outcome', 'outcome_source') if k in d]
        if extra:
            P.append('[REB-STAGE] %s: step 8 has no %s (they belong to step 8-bis)' % (fname, ', '.join(extra)))
    intake_idea = get(data.get('intake.json'), 'idea')
    if text(intake_idea) and norm(d.get('parent_idea')) != norm(intake_idea):
        P.append('[REB-STAGE] %s: parent_idea is not the idea of intake.json' % fname)
    if mode != 'vp' and d.get('header') != HEADER:
        P.append('[HEADER] %s: without VP, "header" must be exactly %r' % (fname, HEADER))
    if mode == 'vp' and 'header' in d:
        P.append('[HEADER] %s: VP is used (intake.json vp.mode = "vp"); remove the "header" field' % fname)
    ids = [i.get('id') for i in ideas]
    for x in sorted({str(i) for i in ids if ids.count(i) > 1}):
        P.append('[REB-STRUCT] %s: duplicate idea id %s' % (fname, x))
    prefix = 'N' if stage == '8' else 'B'
    for i in ids:
        if not (isinstance(i, str) and re.fullmatch(prefix + '[0-9]+', i)):
            P.append('[REB-STRUCT] %s: idea id %r must look like %s1, %s2... in step %s' % (fname, i, prefix, prefix, stage))
    for v in rebound.quota_report(dict(d, stage=stage), cfg)['violations']:
        P.append('[REB-QUOTA] %s: %s' % (fname, v))
    files = {k: v for k, v in data.items()}
    rk0 = d.get('ranking') if isinstance(d.get('ranking'), dict) else None
    sel0 = d.get('selection') if isinstance(d.get('selection'), dict) else None
    bound = (rk0 or {}).get('ranked_utc') or (sel0 or {}).get('decided_utc')    # the search precedes the first of them
    for idea in ideas:
        check_rb_idea(fname, idea, files, mode, vp, P, W, bound if isinstance(bound, str) else None)
    if mode == 'vp':                                       # one VP run per idea: a shared run cannot register two searches
        users = {}
        for i in ideas:
            pa = i.get('prior_art')
            if isinstance(pa, dict) and pa.get('uncontrolled') is not True and text(pa.get('vp_run')):
                users.setdefault(pa['vp_run'].strip(), []).append(str(i.get('id')))
        for run, who in sorted(users.items()):
            if len(who) > 1:
                P.append('[REB-PRIOR-ART] %s: VP run %s serves ideas %s: one VP run per idea' % (fname, run, ', '.join(who)))
    # prior art on every idea before any ranking or choice
    controlled = [i for i in ideas if isinstance(i.get('prior_art'), dict) and i['prior_art'].get('uncontrolled') is not True]
    unchecked = [i.get('id') for i in ideas if isinstance(i.get('prior_art'), dict) and i['prior_art'].get('uncontrolled') is True]
    cap = cfg['rebound']['prior_art_checks_max']
    if len(controlled) > cap:
        P.append('[BUDGET] %s: %d ideas checked, more than the budget per file (%d, config.json rebound.'
                 'prior_art_checks_max); the others are shown as not checked' % (fname, len(controlled), cap))
    if unchecked and len(controlled) < cap:
        P.append('[REB-PRIOR-ART] %s: %s marked not checked for lack of budget, but only %d of %d checks were used'
                 % (fname, ', '.join(map(str, unchecked)), len(controlled), cap))
    rk = d.get('ranking')
    if isinstance(rk, dict) or isinstance(d.get('selection'), dict):
        for i in ideas:
            pa = i.get('prior_art')
            if not isinstance(pa, dict):
                why = 'has no prior-art check'
            elif pa.get('uncontrolled') is True:
                why = 'was not checked (budget used)'
            else:
                gaps = [n for n, ok in (('queries', any(isinstance(q, str) and q.strip() for q in pa.get('queries') or [])),
                                        ('scope', filled(pa.get('scope'), 10)), ('date', isinstance(pa.get('date'), str)))
                        if not ok]
                why = ('has no registered search (%s missing)' % ', '.join(gaps)) if gaps else None
            if why:
                P.append('[REB-ORDER] %s: idea %s %s, yet a ranking or a choice exists: the search of every idea is '
                         'registered first (queries, scope, date), on every idea' % (fname, i.get('id'), why))
    if isinstance(rk, dict):
        for i in ideas:
            pa = i.get('prior_art')
            if isinstance(pa, dict) and isinstance(pa.get('date'), str) and isinstance(rk.get('ranked_utc'), str) \
                    and pa['date'] > rk['ranked_utc']:
                P.append('[REB-ORDER] %s: the prior-art check of %s (%s) is after the ranking (%s): the check precedes any '
                         'ranking' % (fname, i.get('id'), pa['date'], rk['ranked_utc']))
        if not filled(rk.get('basis'), 10):
            P.append('[REB-ORDER] %s: ranking.basis is empty' % fname)
        for k, s in enumerate(rk.get('scenarios') or []):
            if not isinstance(s, dict):
                continue
            for f in ('if', 'then', 'why'):
                if not filled(s.get(f), 5):
                    P.append('[REB-ORDER] %s: ranking.scenarios[%d].%s is empty' % (fname, k, f))
            for x in s.get('prefer') or []:
                if x not in ids:
                    P.append('[REB-ORDER] %s: ranking.scenarios[%d] prefers %r, which is not an idea of the file' % (fname, k, x))
            pref = [x for x in s.get('prefer') or [] if isinstance(x, str)]
            if pref != sorted(set(pref), key=_id_key):
                P.append('[REB-ORDER] %s: ranking.scenarios[%d].prefer must list each idea once, in canonical order of '
                         'identifiers (N1, N2, ...): the order of the list says nothing' % (fname, k))
        novelty_problems('%s ranking' % fname, rk, False, P)
        order_wording_problems('%s ranking' % fname, rk, P)
    for code, msg in rebound.selection_problems(d, cfg):
        P.append('%s %s: %s' % (code, fname, msg))
    sel = d.get('selection') if isinstance(d.get('selection'), dict) else {}
    for iid in sel.get('retained') or []:
        idea = next((i for i in ideas if i.get('id') == iid), None)
        pa = idea.get('prior_art') if isinstance(idea, dict) else None
        if isinstance(pa, dict) and pa.get('status') == 'Exists':
            W.append('[REB-SELECT] %s: %s is retained but prior art says Exists: already done, read it, do not redo it'
                     % (fname, iid))
        if isinstance(pa, dict) and pa.get('uncontrolled') is True:
            W.append('[REB-SELECT] %s: %s is retained but was not checked against prior art' % (fname, iid))
    # duplicates are reported, never removed
    computed = rebound.duplicate_groups(ideas, cfg['rebound']['duplicate_overlap'])
    recorded = [g for g in d.get('duplicate_groups') or [] if isinstance(g, dict)]
    key = lambda g: (tuple(g.get('ids') or []), tuple(sorted(g.get('fields') or [])))   # noqa: E731
    if sorted(map(key, computed)) != sorted(map(key, recorded)):
        P.append('[REB-DUP] %s: duplicate_groups does not match the grouping by mechanism, hypothesis, test and word '
                 'overlap (found %s; recorded %s): run tools/rebound.py groups --write; ideas are never removed'
                 % (fname, [g['ids'] for g in computed] or 'none', [g.get('ids') for g in recorded] or 'none'))
    for g in computed:
        W.append('[REB-DUP] %s: possible duplicates %s (alike by %s): shown to the researcher, not removed'
                 % (fname, ', '.join(g['ids']), ', '.join(g['fields'])))
    if stage == '8-bis':
        check_rb_after(work, fname, d, data, ideas, P)


def check_rb_tree(work, data, P, W):
    present = [f for f in REBOUND_FILES if isinstance(data.get(f), dict)]
    if not present:
        return
    first = data[present[0]]
    path = rebound.tree_path(work, first)
    tree, probs = rebound.load_tree(path)
    if tree is None and not probs:
        W.append('[REB-TREE] no %s at %s: the ideas are not kept for the next session (tools/rebound.py tree --register)'
                 % (rebound.TREE_NAME, path))
        return
    name = Path(work).resolve().name
    if tree is not None and rebound.find_node(tree, name) is None:
        W.append('[REB-TREE] %s is not registered in %s (tools/rebound.py tree --register)' % (name, path))
        return
    for p in probs:
        P.append('[REB-TREE] %s' % p)
    if tree is None:
        return
    for p in rebound.tree_problems(tree):
        P.append('[REB-TREE] %s: %s' % (path.name, p))
    for fname in present:
        d = data[fname]
        sel = d.get('selection') if isinstance(d.get('selection'), dict) else {}
        for idea in d.get('ideas') or []:
            if not isinstance(idea, dict):
                continue
            node = rebound.find_node(tree, name, fname, idea.get('id'))
            if node is None:
                W.append('[REB-TREE] %s %s is not in %s (tools/rebound.py tree --register)' % (fname, idea.get('id'), path.name))
                continue
            want = rebound.status_from(sel, idea.get('id'))
            ok = {'retained': ('retained', 'pursued', 'abandoned'), 'rejected': ('rejected',),
                  'proposed': ('proposed', 'abandoned')}[want]
            if node.get('status') not in ok:
                P.append('[REB-TREE] %s %s: the tree says %r but the selection says %s: keep them together '
                         '(tools/rebound.py select)' % (fname, idea.get('id'), node.get('status'), want))


def check_rebound(work, data, mode, P, W):
    present = [f for f in REBOUND_FILES if isinstance(data.get(f), dict)]
    if not present:
        return
    vp = VPRuns(work, data.get('intake.json')) if mode == 'vp' else None
    for fname in present:
        check_rb_file(work, fname, data[fname], data, mode, vp, P, W)
    card_cap = common.config()['rebound']['prior_art_checks_card_max']
    checked = sum(1 for f in present for i in (data[f].get('ideas') or []) if isinstance(i, dict)
                  and isinstance(i.get('prior_art'), dict) and i['prior_art'].get('uncontrolled') is not True)
    if checked > card_cap:
        P.append('[BUDGET] rebound files: %d ideas checked, more than the budget per card (%d, config.json rebound.'
                 'prior_art_checks_card_max)' % (checked, card_cap))
    if vp is not None:
        for where, ref, _ in iter_refs(data):
            if not where.startswith(tuple(REBOUND_FILES)):
                continue
            status, _, _ = ref_check(vp, ref)
            if status in UNVERIFIED_STATUSES + ('DISTORTED',):
                W.append('[REB-REF] %s: %s is %s in the VP verification: not a verified reference, read it before relying on '
                         'it' % (where, ref.get('id'), status))
    check_rb_tree(work, data, P, W)


# ---------------------------------------------------------------- history (step 0-bis "Already tried here")

HISTORY = 'history.json'
HISTORY_COND_MIN = 40        # condition_met: at least 40 characters, no placeholder
HISTORY_WHY_MIN = 20
ITEM_SKIP = {'tests.json': ('traps', 'simulation', 'internal_history', 'id'),
             'rebound': ('prior_art', 'materials', 'internal_history', 'id')}


def project_dirs(intake):
    dirs = get(intake, 'project_dirs')
    return [d for d in dirs if isinstance(d, str) and d.strip()] if isinstance(dirs, list) else []


def _resolve_dir(d, work):
    p = Path(d).expanduser()
    return p if p.is_absolute() else Path(work) / p


def _skip_strings(x, skip):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            if k not in skip:
                for s in _skip_strings(v, skip):
                    yield s
    elif isinstance(x, list):
        for v in x:
            for s in _skip_strings(v, skip):
                yield s


def history_items(data):
    """[(file name, item id, item dict, skipped keys)] : the tests of tests.json and the ideas of the rebound files."""
    out = []
    tj = data.get('tests.json')
    for t in (tj.get('tests') if isinstance(tj, dict) else None) or []:
        if isinstance(t, dict):
            out.append(('tests.json', t.get('id'), t, ITEM_SKIP['tests.json']))
    for fname in REBOUND_FILES:
        rb = data.get(fname)
        for i in (rb.get('ideas') if isinstance(rb, dict) else None) or []:
            if isinstance(i, dict):
                out.append((fname, i.get('id'), i, ITEM_SKIP['rebound']))
    return out


class HistoryIndex:
    """history.json read for the checks: entries by id, the terms of its queries, overlap of an item with an entry."""

    def __init__(self, hist, work, dirs):
        self.hist = hist
        self.work = work
        self.roots = [_resolve_dir(d, work) for d in dirs]
        self.entries = [e for e in hist.get('entries') or [] if isinstance(e, dict)]
        self.by_id = {e.get('id'): e for e in self.entries}
        self.terms = {}                     # folded canonical term -> [term dicts of every query]
        for q in hist.get('queries') or []:
            for t in (q.get('terms') if isinstance(q, dict) else None) or []:
                if isinstance(t, dict) and isinstance(t.get('term'), str):
                    self.terms.setdefault(common.fold(t['term']), []).append(t)
        self._pat = {}

    def variants(self, e):
        """Words (term and synonyms) that make a text overlap entry e: the non-generic terms of e."""
        out = []
        for canon in e.get('terms') or []:
            for t in self.terms.get(common.fold(canon), []):
                if not t.get('generic'):
                    out += [t['term']] + [s for s in t.get('synonyms') or [] if isinstance(s, str)]
        return out

    def overlaps(self, e, item_id, text):
        if item_id in (e.get('for') or []):
            return True
        folded = common.fold(text)
        for v in self.variants(e):
            p = self._pat.get(v)
            if p is None:
                p = self._pat[v] = common.term_pattern(v) or False
            if p and p.search(folded):
                return True
        return False

    def generic_terms(self):
        return sorted({t['term'] for ts in self.terms.values() for t in ts if t.get('generic')})

    def source_line(self, src):
        """The text of line N of file F (F:N, inside a project folder, no link), or None."""
        m = re.match(r'^(.+):([0-9]+)$', text(src))
        if not m:
            return None
        rel, n = m.group(1), int(m.group(2))
        if Path(rel).is_absolute() or '..' in Path(rel).parts:
            return None
        for root in self.roots:
            p = root / rel
            try:
                p.resolve().relative_to(root.resolve())
                if p.is_symlink() or not p.is_file() or p.stat().st_size > 5000000:
                    continue
                lines = p.read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n').split('\n')
            except (OSError, ValueError):
                continue
            if 1 <= n <= len(lines):
                return lines[n - 1]
        return None


def _entry_cite(e):
    return '%s:%d' % (e.get('file'), e.get('line')) if isinstance(e.get('line'), int) else str(e.get('file'))


def check_cites(tag, items, idx, P):
    """Validate the internal_history items of one test or idea; returns the set of (root, file) of the valid citations."""
    covered = set()
    for i, it in enumerate(items if isinstance(items, list) else []):
        where = '%s internal_history[%d]' % (tag, i)
        if not isinstance(it, dict):
            P.append('[HISTORY-CITE] %s: must be an object' % where)
            continue
        probs = []
        e = idx.by_id.get(it.get('entry'))
        if e is None:
            probs.append('entry %r is not an entry of history.json' % it.get('entry'))
        else:
            if text(it.get('cited')) != _entry_cite(e):
                probs.append('cited %r is not the file:line of entry %s (%s)' % (it.get('cited'), e.get('id'),
                                                                                 _entry_cite(e)))
            vq = common.norm_ws(text(it.get('verdict_quoted')))
            shown = common.norm_ws('%s %s' % (e.get('excerpt'), e.get('verdict_excerpt') or ''))
            marks = [common.norm_ws(m) for m in e.get('markers') or []]
            if not vq or not (vq in shown or vq in marks):
                probs.append('verdict_quoted %r is not a verdict written in entry %s (quote it word for word from the '
                             'file)' % (it.get('verdict_quoted'), e.get('id')))
            rc = text(it.get('reopen_condition'))
            src = it.get('reopen_condition_source')
            if common.is_placeholder(rc, 20):
                probs.append('reopen_condition is empty or a placeholder: quote the written condition (when none is '
                             'written the trial may not be reopened: remove the item)')
            elif text(src):
                line = idx.source_line(src)
                if line is None:
                    probs.append('reopen_condition_source %r is not a readable file:line inside a project folder' % src)
                elif common.norm_ws(rc) not in common.norm_ws(line):
                    probs.append('reopen_condition is not written at %s' % src)
            elif not e.get('reopen_condition'):
                probs.append('entry %s has no written reopening condition: give reopen_condition_source (file:line of the '
                             'file that states it), or remove the item' % e.get('id'))
            elif common.norm_ws(rc) not in common.norm_ws(e['reopen_condition']):
                probs.append('reopen_condition is not the condition written in entry %s' % e.get('id'))
        if it.get('decision') != 'kept':
            probs.append('decision must be "kept" (a removed item is not kept: delete it, and note it in '
                         'internal_history_removed)')
        if common.is_placeholder(it.get('condition_met'), HISTORY_COND_MIN):
            probs.append('condition_met must explain, in at least %d characters, why the written reopening condition is '
                         'met now' % HISTORY_COND_MIN)
        for p in probs:
            P.append('[HISTORY-CITE] %s: %s' % (where, p))
        if not probs and e is not None:
            covered.add((e.get('root'), e.get('file')))
    return covered


def check_removed(fname, d, idx, P):
    """A removal cites the passage by file:line, read again in the project folder (the entry may vanish from history.json
    when the terms of the tests change after the removal)."""
    for i, n in enumerate((d.get('internal_history_removed') if isinstance(d, dict) else None) or []):
        where = '%s internal_history_removed[%d]' % (fname, i)
        if not isinstance(n, dict):
            P.append('[HISTORY-CITE] %s: must be an object' % where)
            continue
        if idx.source_line(n.get('cited')) is None:
            P.append('[HISTORY-CITE] %s: cited %r is not a readable file:line inside a project folder' % (where, n.get('cited')))
        if len(text(n.get('what'))) < 3:
            P.append('[HISTORY-CITE] %s: "what" must say what was removed' % where)
        if common.is_placeholder(n.get('why'), HISTORY_WHY_MIN):
            P.append('[HISTORY-CITE] %s: "why" must say, in at least %d characters, why it was removed'
                     % (where, HISTORY_WHY_MIN))


def leak_secrets(hist, intake, k):
    """({shingle: entry id}, [(text, label)]): what of history.json must not appear in a request. The words of the
    user's own idea and of the query terms are not secrets."""
    own = set()
    texts = [text(get(intake, 'idea')), text(get(intake, 'domain'))]
    for q in hist.get('queries') or []:
        for t in (q.get('terms') if isinstance(q, dict) else None) or []:
            if isinstance(t, dict):
                texts += [text(t.get('term'))] + [s for s in t.get('synonyms') or [] if isinstance(s, str)]
    for t in texts:
        w = common.words(t)
        own.update(tuple(w[i:i + k]) for i in range(len(w) - k + 1))
    shingles, paths = {}, []
    for e in hist.get('entries') or []:
        if not isinstance(e, dict):
            continue
        for f in ('excerpt', 'verdict_excerpt', 'reopen_condition'):
            w = common.words(text(e.get(f)))
            for i in range(len(w) - k + 1):
                sh = tuple(w[i:i + k])
                if sh not in own:
                    shingles.setdefault(sh, 'entry %s, %s' % (e.get('id'), _entry_cite(e)))
        rel = text(e.get('file'))
        if '/' in rel or len(rel) >= 12:
            paths.append((common.fold(rel), '%s (entry %s)' % (rel, e.get('id'))))
    for d in hist.get('project_dirs') or []:
        if isinstance(d, str) and len(d) >= 4 and ('/' in d or '\\' in d):
            paths.append((common.fold(d), 'the project folder %s' % d))
    return shingles, paths


def request_sources(work, data):
    """[(label, text)]: every place where the host's words leave for VP, the search tools or another model."""
    out = []
    intake = data.get('intake.json')
    runs = get(intake, 'vp', 'runs')
    for name, path in sorted(runs.items()) if isinstance(runs, dict) else []:
        if not isinstance(path, str):
            continue
        d = Path(path) if Path(path).is_absolute() else work / path
        for rel in ('state/journal.jsonl', 'scope.md'):
            try:
                out.append(('VP run %s: %s' % (name, rel), (d / rel).read_text(encoding='utf-8', errors='replace')))
            except OSError:
                pass
    pa = data.get('prior_art.json')
    if isinstance(pa, dict) and isinstance(pa.get('searched'), str):
        out.append(('prior_art.json searched', pa['searched']))
    for fname in REBOUND_FILES:
        rb = data.get(fname)
        for i in (rb.get('ideas') if isinstance(rb, dict) else None) or []:
            p = i.get('prior_art') if isinstance(i, dict) else None
            if isinstance(p, dict):
                out.append(('%s %s prior_art queries' % (fname, i.get('id')), '\n'.join(map(str, p.get('queries') or []))))
                out.append(('%s %s prior_art scope' % (fname, i.get('id')), str(p.get('scope') or '')))
    try:                                     # what tools/matter.py sent through the gateway (material, moment)
        out.append(('matter/state/journal.jsonl', (work / 'matter' / 'state' / 'journal.jsonl').read_text(
            encoding='utf-8', errors='replace')))
    except OSError:
        pass
    pack = work / 'critique-pack'
    if pack.is_dir():
        for p in sorted(pack.glob('*.md')):
            try:
                out.append(('critique-pack/%s' % p.name, p.read_text(encoding='utf-8', errors='replace')))
            except OSError:
                pass
    return out


def check_history_leak(work, data, hist, P, code='[HISTORY-LEAK]'):
    k = max(2, int(common.config()['history'].get('leak_shingle_words', 5)))
    shingles, paths = leak_secrets(hist, data.get('intake.json'), k)
    for label, body in request_sources(work, data):
        w = common.words(body)
        found = None
        for i in range(len(w) - k + 1):
            sh = tuple(w[i:i + k])
            if sh in shingles:
                found = 'a passage of %s' % shingles[sh]
                break
        if found is None:
            folded = common.fold(body)
            for p, name in paths:
                if p and p in folded:
                    found = name
                    break
        if found:
            P.append('%s %s: holds text from your project archives (%s): the archives stay local and never '
                     'enter a request; write the request again from the words of the idea only' % (code, label, found))


def check_history(work, data, P, W):
    intake = data.get('intake.json')
    dirs = project_dirs(intake)
    if not dirs:
        return                              # not checked: the card says so
    hp = work / HISTORY
    if not hp.exists():
        P.append('[HISTORY-MISSING] %s: intake.json gives project_dirs, so step 0-bis must run: python3 -I <SKILL_DIR>/tools/'
                 'history.py scan <dir> --label intake ...' % HISTORY)
        return
    try:
        hist = read_json(hp)
    except (ValueError, UnicodeDecodeError) as e:
        P.append('[JSON] %s: %s' % (HISTORY, e))
        return
    errs = schema_lite.validate(hist, read_json(SCHEMAS / HISTORY))
    for e in errs:
        P.append('[SCHEMA] %s: %s' % (HISTORY, e))
    if errs:
        return
    if hist.get('project_dirs') != dirs:
        P.append('[HISTORY-STALE] %s: it was made for the project folders %s but intake.json now says %s: run tools/history.py '
                 'scan again' % (HISTORY, hist.get('project_dirs'), dirs))
    labels = {q.get('label'): q for q in hist.get('queries') or []}
    items = history_items(data)
    need = ['intake']
    if any(f == 'tests.json' for f, _, _, _ in items):
        need.append('tests')
    if any(f != 'tests.json' for f, _, _, _ in items):
        need.append('rebound')
    for lb in need:
        if lb not in labels:
            P.append('[HISTORY-QUERY] %s: no "%s" query: run tools/history.py scan --label %s on the terms of that step '
                     '(SKILL.md step 0-bis)' % (HISTORY, lb, lb))
    fors = {lb: {t.get('for') for t in (labels[lb].get('terms') or [])} for lb in ('tests', 'rebound') if lb in labels}
    for fname, iid, _, _ in items:
        lb = 'tests' if fname == 'tests.json' else 'rebound'
        if lb in fors and iid not in fors[lb]:
            P.append('[HISTORY-QUERY] %s: %s %s has no term "for": %r in the "%s" query: search the archives for the subject '
                     'of every test and idea' % (HISTORY, 'test' if lb == 'tests' else 'idea', iid, iid, lb))
    idx = HistoryIndex(hist, work, dirs)
    for fname in ['tests.json'] + list(REBOUND_FILES):
        check_removed(fname, data.get(fname), idx, P)     # the note cites file:line: it survives a new scan
    for fname, iid, obj, skip in items:
        tag = '%s %s' % (fname, iid)
        covered = check_cites(tag, obj.get('internal_history'), idx, P)
        body = '\n'.join(_skip_strings(obj, skip))
        hits = [e for e in idx.entries if e.get('verdict') == 'classed' and idx.overlaps(e, iid, body)]
        per_file = {}
        for e in hits:
            per_file.setdefault((e.get('root'), e.get('file')), []).append(e)
        todo = [(k, v) for k, v in sorted(per_file.items(), key=lambda kv: str(kv[0])) if k not in covered]
        if todo:
            what = '; '.join('%s (%s)' % (k[1], ', '.join('%s line %s: %s%s' % (
                e.get('id'), e.get('line'), '/'.join(e.get('markers') or [])[:60],
                ('; reopening: %s' % text(e.get('reopen_condition'))[:80]) if e.get('reopen_condition') else '; no written '
                'reopening condition') for e in v[:2])) for k, v in todo)
            P.append('[HISTORY-OVERLAP] %s overlaps a trial already CLASSED in your own archives: %s. Remove it (note it in '
                     'internal_history_removed), or keep it with internal_history citing each of these files (entry, cited, '
                     'verdict_quoted, reopen_condition, condition_met: the written reopening condition and why it is met now)'
                     % (tag, what))
    gen = idx.generic_terms()
    if gen:
        W.append('[HISTORY-OVERLAP] terms marked generic are not used to find an overlap with a test or an idea: %s'
                 % ', '.join(gen))
    check_history_leak(work, data, hist, P)


# ---------------------------------------------------------------- hybrid free draft (step 0-ter)


def _strong(statuses):
    return 'verified' in statuses


def check_draft(work, data, mode, P):
    fp = work / 'free_draft.md'
    if not fp.exists():
        return                                   # no free draft: nothing to check (the card says nothing)
    try:
        draft = fp.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as e:
        P.append('[DRAFT-EMPTY] free_draft.md: unreadable (%s)' % e)
        return
    if len(draft.strip()) < DRAFT_MIN_CHARS:
        P.append('[DRAFT-EMPTY] free_draft.md: %d characters; the free phase writes what the host knows, at least %d '
                 'characters' % (len(draft.strip()), DRAFT_MIN_CHARS))
    cj = data.get('draft_claims.json')
    if not (work / 'draft_claims.json').exists():
        P.append('[DRAFT-MISSING] draft_claims.json: free_draft.md exists, so every claim and reference of the draft must be '
                 'verified, marked "unverified (memory)" or removed there (python3 -I <SKILL_DIR>/tools/hybrid.py stub <dir>)')
        return
    if not isinstance(cj, dict) or not isinstance(cj.get('claims'), list):
        return                                   # [JSON] or [SCHEMA] already says why
    if guards.is_v2(work):
        check_draft_submissions(work, draft, cj, P)
    sha = common.sha256_file(fp)
    if cj.get('draft_sha256') != sha:
        P.append('[DRAFT-STALE] draft_claims.json: draft_sha256 is not the SHA-256 of the current free_draft.md (the draft '
                 'changed after its claims were written)')
    # order: the draft is sealed by a "free_draft" step before the first VP run
    steps = []
    try:
        rj = read_json(work / RUN)
        steps = [s for s in rj.get('steps', []) if isinstance(s, dict)]
    except (OSError, ValueError, AttributeError):
        pass
    idx = [i for i, s in enumerate(steps) if s.get('step') == 'free_draft']
    if not idx:
        P.append('[DRAFT-ORDER] %s: no "free_draft" step: record it before any VP run (tools/step.py --step free_draft)' % RUN)
    else:
        first_vp = next((i for i, s in enumerate(steps) if s.get('step') in ('vp_run', 'rebound_vp_run')), None)
        if first_vp is not None and idx[0] > first_vp:
            P.append('[DRAFT-ORDER] %s: the "free_draft" step comes after a VP run: the free phase is written first' % RUN)
        if steps[idx[0]].get('sha256') != sha:
            P.append('[DRAFT-STALE] %s: the free_draft step recorded another SHA-256 than the current free_draft.md' % RUN)
    vp = VPRuns(work, data.get('intake.json')) if mode == 'vp' else None
    valid = {}
    spans = {}
    for c in cj['claims']:
        if not isinstance(c, dict):
            continue
        cid = c.get('id')
        if hybrid.quote_span(draft, c.get('quote')) is None:
            P.append('[DRAFT-QUOTE] draft_claims.json %s: the quote is not a passage of free_draft.md (copy it word for '
                     'word)' % cid)
        spans[cid] = c
        if c.get('status') == 'verified':
            if mode != 'vp':
                P.append('[DRAFT-NOVP] draft_claims.json %s: "verified" needs VP; without VP a claim of the draft is '
                         '"unverified_memory" or "removed"' % cid)
                valid[cid] = False
                continue
            ref = c.get('ref')
            if not isinstance(ref, dict):
                P.append('[DRAFT-VERIFY] draft_claims.json %s: "verified" needs ref = {id, run, claim} of a VP run' % cid)
                valid[cid] = False
                continue
            status, code, msg = ref_check(vp, ref)
            if code:
                P.append('[DRAFT-VERIFY] draft_claims.json %s: %s %s: %s' % (cid, code, ref.get('id'), msg))
                valid[cid] = False
            else:
                valid[cid] = True
    # what the card takes up from the draft
    rows = hybrid.analyse(draft, cj['claims'], data, strict=guards.is_r3(work))
    for row in rows:
        if not row['taken_up_in']:
            continue
        cov = [spans[i] for i in row['covered_by'] if i in spans]
        where = ', '.join(sorted({'%s %s' % (t['file'], t['path']) for t in row['taken_up_in']}))[:160]
        if not cov:
            P.append('[DRAFT-UNMARKED] the draft item %r is taken up in %s but no claim of draft_claims.json covers it: '
                     'verify it (VP), mark it "unverified (memory)" or remove it' % (row['text'], where))
            continue
        ok_ver = any(c.get('status') == 'verified' and valid.get(c.get('id')) for c in cov)
        if ok_ver:
            continue
        if any(c.get('status') == 'verified' for c in cov):
            continue                              # an invalid verification is reported above
        if any(c.get('status') == 'unverified_memory' for c in cov):
            bad = [t for t in row['taken_up_in'] if not t['marked']]
            if bad:
                P.append('[DRAFT-MARK] the draft item %r is only "unverified_memory" and is taken up without the mark '
                         '"%s" in %s' % (row['text'], hybrid.MARK, ', '.join(sorted({'%s %s' % (t['file'], t['path']) for t in bad}))[:160]))
            continue
        P.append('[DRAFT-REMOVED] the draft item %r was removed (draft_claims.json) but is taken up in %s' % (row['text'], where))


def check_draft_submissions(work, draft, cj, P):
    """v2r2: verification attempts are distinct from successful factual support."""
    rows = hybrid.submissions(work)
    submitted = [r for r in rows if r['submitted']]
    count = max(len(cj['claims']), len(hybrid.draft_quotes(draft)))
    if len(cj['claims']) < len(hybrid.draft_quotes(draft)):
        P.append('[DRAFT-INVENTORY] draft_claims.json lists %d claims but free_draft.md has %d sentences; '
                 'the missing ones are neither verified nor kept as leads' % (len(cj['claims']), len(hybrid.draft_quotes(draft))))
    if count >= 5 and not submitted:
        P.append('[DRAFT-NOSUBMIT] free_draft.md has at least five claims but none entered a VP card; '
                 'the host must submit the five most important decision claims with hybrid.py submit')
    if len(submitted) < min(5, count):
        P.append('[DRAFT-PRIORITY] select the five decision priorities (all if fewer): %d submitted; '
                 'other leads remain unverified (memory)' % len(submitted))
    for row in rows:
        if row['error']:
            P.append('[DRAFT-SUBMISSION] %s: %s' % (row['id'], row['error']))
        elif row['submitted'] and row['verdict'] is None:
            P.append('[DRAFT-VERDICT] %s: entered the VP card but has no verdict yet; run VP verification' % row['id'])
    if any(c.get('status') == 'removed' for c in cj['claims'] if isinstance(c, dict)):
        P.append('[DRAFT-RETAIN] removed draft entries remain visible as unverified (memory) leads in v2; '
                 'keep their status and any contrary evidence explicit')


def draft_counts(work):
    """{status: n} of draft_claims.json, or None when there is no free draft."""
    if not (work / 'free_draft.md').exists():
        return None
    try:
        cj = read_json(work / 'draft_claims.json')
    except (OSError, ValueError):
        return None
    out = {'verified': 0, 'unverified_memory': 0, 'removed': 0}
    for c in cj.get('claims') or [] if isinstance(cj, dict) else []:
        if isinstance(c, dict) and c.get('status') in out:
            out[c['status']] += 1
    return out


# ---------------------------------------------------------------- project context (step 0-quater)


def check_context(work, data, P, W):
    intake = data.get('intake.json')
    ctx = get(intake, 'context')
    if isinstance(ctx, dict):
        kns = [k for k in ctx.get('key_numbers') or [] if isinstance(k, dict)]
        dirs = project_dirs(intake)
        idx = HistoryIndex({}, work, dirs) if dirs else None
        for k in kns:
            if k.get('source') != 'extracted':
                continue
            where = 'intake.json context.key_numbers %s' % k.get('name')
            if k.get('confirmed') is not True:
                P.append('[CONTEXT-CONFIRM] %s: an extracted number is used only once the host confirms it '
                         '(python3 -I <SKILL_DIR>/tools/context.py confirm)' % where)
                continue
            line = idx.source_line(k.get('cited')) if idx else None
            if line is None:
                P.append('[CONTEXT-CITE] %s: cited %r is not a readable file:line inside a project folder' % (where, k.get('cited')))
                continue
            found = [float(x.replace(',', '.')) for x in re.findall(r'\d+(?:[.,]\d+)?', line)]
            if not any(abs(f - float(k.get('value'))) < 1e-9 for f in found):
                P.append('[CONTEXT-CITE] %s: line %s does not hold the value %s (the file changed, or the line was '
                         'mistaken)' % (where, k.get('cited'), k.get('value')))
    # power on the real numbers: a simulation that says it used the context carries the confirmed value
    ci = common.context_inputs(intake)
    tj = data.get('tests.json')
    for t in (tj.get('tests') if isinstance(tj, dict) else None) or []:
        simb = get(t, 'sensitivity', 'simulation')
        if not isinstance(simb, dict) or not isinstance(t, dict):
            continue
        tag = 'tests.json %s' % t.get('id')
        cb = simb.get('context') if isinstance(simb.get('context'), dict) else {}
        inputs = cb.get('inputs') if isinstance(cb.get('inputs'), dict) else {}
        if cb.get('used') is True:
            for param, info in inputs.items():
                want = ci.get(param)
                got = info.get('value') if isinstance(info, dict) else None
                if want is None:
                    P.append('[CONTEXT-SIM] %s: the simulation says its %s comes from the context, but intake.json has no '
                             'confirmed key number for it' % (tag, param))
                elif got != want['value'] or simb.get(param) != want['value']:
                    P.append('[CONTEXT-SIM] %s: simulation %s is %r (context says %r) but the confirmed key number %s is %r'
                             % (tag, param, simb.get(param), got, want['name'], want['value']))
        if 'n' in ci and 'n' not in inputs:
            W.append('[CONTEXT-POWER] %s: the simulation does not use the project\'s n (%s = %s, intake.json context); '
                     'rerun tools/sim.py with --context <dir>, or say why in its context block'
                     % (tag, ci['n']['name'], ci['n']['value']))
    cp = work / 'context_candidates.json'
    if cp.exists() and project_dirs(intake):
        try:
            cc = read_json(cp)
        except (ValueError, UnicodeDecodeError) as e:
            P.append('[JSON] context_candidates.json: %s' % e)
            return
        for e in schema_lite.validate(cc, read_json(SCHEMAS / 'context_candidates.json')):
            P.append('[SCHEMA] context_candidates.json: %s' % e)
        pseudo = {'entries': [{'id': c.get('id'), 'file': c.get('file'), 'line': c.get('line'), 'excerpt': c.get('excerpt')}
                              for c in (cc.get('candidates') if isinstance(cc, dict) else None) or [] if isinstance(c, dict)],
                  'queries': [], 'project_dirs': project_dirs(intake)}
        check_history_leak(work, data, pseudo, P, code='[CONTEXT-LEAK]')


# ---------------------------------------------------------------- expected effects (step 2-bis)


def check_evidence(work, data, P, W):
    ev = data.get('evidence_table.json')
    if not isinstance(ev, dict):
        return
    hy = data.get('hypotheses.json')
    leads = [h.get('id') for h in (hy.get('hypotheses') if isinstance(hy, dict) else None) or [] if isinstance(h, dict)]
    entries = [e for e in ev.get('entries') or [] if isinstance(e, dict)]
    covered = {e.get('lead') for e in entries}
    for n in ev.get('no_evidence') or []:
        if isinstance(n, dict):
            if common.is_placeholder(n.get('searched'), 20):
                P.append('[EVID-COVER] evidence_table.json no_evidence %s: "searched" must say what was searched (at least '
                         '20 characters): "no measured effect found" is never a proof of absence' % n.get('lead'))
            else:
                covered.add(n.get('lead'))
    for lead in leads:
        if lead not in covered:
            P.append('[EVID-COVER] evidence_table.json: no entry (and no "no_evidence" note with what was searched) for the '
                     'main lead %s' % lead)
    for e in entries:
        tag = 'evidence_table.json %s' % e.get('id')
        if e.get('lead') not in leads:
            P.append('[EVID-COVER] %s: lead %r is not a load-bearing hypothesis of hypotheses.json' % (tag, e.get('lead')))
        if common.is_placeholder(e.get('sample'), 8):
            P.append('[EVID-FIELD] %s: sample must say what was measured and on what (8 characters or more, no placeholder)' % tag)
        me = e.get('measured_effect') if isinstance(e.get('measured_effect'), dict) else {}
        has_effect = isinstance(me.get('value'), (int, float)) and not isinstance(me.get('value'), bool)
        if has_effect:
            if not text(me.get('unit')):
                P.append('[EVID-FIELD] %s: measured_effect.value needs its unit' % tag)
        elif common.is_placeholder(me.get('not_reported'), 12):
            P.append('[EVID-FIELD] %s: measured_effect holds neither a value (with unit) nor a written not_reported reason' % tag)
        src = e.get('source')
        if has_effect and not (isinstance(src, dict) and text(src.get('id'))):
            P.append('[EVID-SOURCE] %s: a measured effect needs its source (a reference read through VP)' % tag)
        nts = e.get('needed_test_size')
        if isinstance(nts, dict) and 'not_computable' in nts:
            if common.is_placeholder(nts.get('not_computable'), 20):
                P.append('[EVID-SIZE] %s: not_computable needs its reason (20 characters or more)' % tag)
        elif isinstance(nts, dict) and nts.get('mode') == 'needed_n':
            try:
                diffs = sim.compare_needed_n(nts, sim.rerun_needed_n(nts))
            except (ValueError, KeyError, TypeError) as ex:
                diffs = ['cannot be rerun (%s)' % ex]
            for d in diffs:
                P.append('[EVID-SIZE] %s: needed_test_size differs from tools/sim.py rerun: %s (never write it by hand)' % (tag, d))
        elif has_effect:
            P.append('[EVID-SIZE] %s: a measured effect needs needed_test_size, written by tools/sim.py --needed-n '
                     '--write-into evidence_table.json --entry %s (or {"not_computable": reason})' % (tag, e.get('id')))
        elif nts is not None:
            P.append('[EVID-SIZE] %s: needed_test_size is neither a tools/sim.py --needed-n block nor {not_computable}' % tag)


# ---------------------------------------------------------------- matter and moment (step 1-bis)


def _inside(work, rel):
    p = Path(rel) if isinstance(rel, str) else None
    if p is None or p.is_absolute() or '..' in p.parts:
        return None
    return Path(work) / p


def _read_envelope(work, rel, sha, tag, T, P, code='[MAT-ENVELOPE]'):
    """The saved gateway envelope (dict) when it exists, matches its hash and was made at a T not after T; else None."""
    p = _inside(work, rel)
    if p is None or not p.is_file():
        P.append('%s %s: the gateway envelope %r is missing (it is kept under matter/)' % (code, tag, rel))
        return None
    if common.sha256_file(p) != sha:
        P.append('%s %s: the envelope %s does not match its SHA-256 (changed after it was saved)' % (code, tag, rel))
        return None
    try:
        env = read_json(p)
    except (ValueError, UnicodeDecodeError):
        P.append('%s %s: the envelope %s is not JSON' % (code, tag, rel))
        return None
    if T and text(env.get('T')) > T:
        P.append('[DATE] %s: the gateway call ran with T %s, after the T of the idea (%s)' % (tag, env.get('T'), T))
    return env if isinstance(env, dict) else None


def check_matter_journal(work, T, P):
    jp = work / 'matter' / 'state' / 'journal.jsonl'
    if not jp.exists():
        P.append('[MAT-ENVELOPE] matter/state/journal.jsonl: the gateway journal of the matter and moment calls is missing')
        return
    late = set()
    for line in jp.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and T and text(e.get('T')) > T:
            late.add(e.get('T'))
    if late:
        P.append('[DATE] matter/state/journal.jsonl: gateway calls with T %s, after the T of the idea (%s)'
                 % (', '.join(sorted(late)), T))


def check_material(work, data, P, W):
    mat = data.get('material.json')
    if not isinstance(mat, dict):
        return
    intake = data.get('intake.json')
    T = text(get(intake, 'T'))
    targets = ['main']
    for fname in REBOUND_FILES:
        rb = data.get(fname)
        targets += [i.get('id') for i in (rb.get('ideas') if isinstance(rb, dict) else None) or [] if isinstance(i, dict)]
    items = [i for i in mat.get('items') or [] if isinstance(i, dict)]
    gateway_used = False
    for n, it in enumerate(items):
        tag = 'material.json %s %s' % (it.get('for'), it.get('name'))
        if it.get('for') not in targets:
            P.append('[MAT-FOR] %s: %r is neither "main" nor an idea of a rebound file (%s)' % (tag, it.get('for'), ', '.join(map(str, targets))))
        if not text(it.get('licence')):
            P.append('[MAT-FIELD] %s: licence is missing (write "unknown" when the source does not say)' % tag)
        la = it.get('last_activity')
        if isinstance(la, str) and T and la > T:
            P.append('[DATE] %s: last_activity %s is after T (%s): nothing after T is used' % (tag, la, T))
        if it.get('via') == 'host':
            W.append('[MAT-HOST] %s: not verified: found by the host\'s own search, not through VP\'s gateway' % tag)
            continue
        gateway_used = True
        env = _read_envelope(work, it.get('envelope'), it.get('envelope_sha256'), tag, T, P)
        if env is None:
            continue
        gw = env.get('gateway')
        if it.get('kind') == 'code' and env.get('command') == 'repo-info':
            info = matter.extract_repo_info(gw, T)
            for k_item, k_info in (('licence', 'licence'), ('last_activity', 'last_activity'),
                                   ('last_activity_basis', 'last_activity_basis')):
                if it.get(k_item) != info.get(k_info):
                    P.append('[MAT-ENVELOPE] %s: %s is %r but the envelope gives %r (extracted, never typed)'
                             % (tag, k_item, it.get(k_item), info.get(k_info)))
        else:
            cands = {c['name']: c for c in matter.extract_candidates(gw)}
            c = cands.get(it.get('name'))
            if c is None:
                P.append('[MAT-ENVELOPE] %s: %r is not in the envelope %s' % (tag, it.get('name'), it.get('envelope')))
            elif (c.get('licence') or 'unknown') != it.get('licence'):
                P.append('[MAT-ENVELOPE] %s: licence is %r but the envelope gives %r' % (tag, it.get('licence'), c.get('licence') or 'unknown'))
    for s in mat.get('searched') or []:
        if isinstance(s, dict) and s.get('envelope'):
            gateway_used = True
    if gateway_used:
        check_matter_journal(work, T, P)
    have = {it.get('for') for it in items}
    for s in mat.get('searched') or []:
        if isinstance(s, dict) and s.get('result') == 'not found' and any(text(q) for q in s.get('queries') or []):
            have.add(s.get('for'))
    for tgt in targets:
        if tgt not in have:
            P.append('[MAT-COVER] material.json: no code, dataset or benchmark and no recorded "not found" search (with its '
                     'queries) for %s' % tgt)
    opt = mat.get('optional_sources') if isinstance(mat.get('optional_sources'), dict) else {}
    cfg = common.config()
    for key, label, conf in (('catalogue', 'catalogue', cfg.get('catalogue')), ('directions', 'directions index', cfg.get('directions_index'))):
        o = opt.get(key)
        if not isinstance(o, dict) or o.get('status') not in ('used', 'skipped'):
            P.append('[MAT-OPTIONAL] material.json optional_sources.%s: must say "used" or "skipped" (python3 -I '
                     '<SKILL_DIR>/tools/matter.py optional <dir>)' % key)
            continue
        if o['status'] == 'skipped':
            if common.is_placeholder(o.get('reason'), 20):
                P.append('[MAT-OPTIONAL] material.json optional_sources.%s: a skipped source says why (20 characters or more)' % key)
            if conf and Path(conf).expanduser().is_file():
                W.append('[MAT-OPTIONAL] the %s is configured (%s) but was skipped: run tools/matter.py optional again' % (label, conf))
            continue
        path = Path(str(o.get('path') or '')).expanduser()
        if not path.is_file():
            W.append('[MAT-OPTIONAL] the %s used here (%s) is not readable on this machine: its matches cannot be rechecked' % (label, o.get('path')))
            continue
        if key == 'catalogue':
            known = {r.get('id') for r in matter.read_catalogue(path)}
            for m in o.get('matches') or []:
                if isinstance(m, dict) and m.get('id') not in known:
                    P.append('[MAT-CATALOGUE] material.json: match %r is not a row of the catalogue %s' % (m.get('id'), path))
        else:
            known = {(r.get('direction'), r.get('year')) for r in matter.read_directions(path)}
            for m in o.get('matches') or []:
                if isinstance(m, dict) and (m.get('direction'), str(m.get('year'))) not in {(a, str(b)) for a, b in known}:
                    P.append('[MAT-CATALOGUE] material.json: direction %r is not a list-A row of the index %s' % (m.get('direction'), path))


def check_moment(work, data, P, W):
    mo = data.get('moment.json')
    if not isinstance(mo, dict):
        return
    T = text(get(data.get('intake.json'), 'T'))
    series = [s for s in mo.get('series') or [] if isinstance(s, dict)]
    ok = True
    if len(series) < 4:
        P.append('[MOMENT-SERIES] moment.json: %d dated total(s); at least 4 are needed to read a moment' % len(series))
        ok = False
    dates = [text(s.get('as_of')) for s in series]
    if dates != sorted(set(dates)):
        P.append('[MOMENT-SERIES] moment.json: the dates must be strictly increasing')
        ok = False
    tots = [s.get('total') for s in series]
    if any(not isinstance(t, (int, float)) for t in tots) or any(b < a for a, b in zip(tots, tots[1:])):
        P.append('[MOMENT-SERIES] moment.json: the totals are cumulative (publications before each date): they never decrease')
        ok = False
    if T and dates and dates[-1] > T:
        P.append('[MOMENT-SERIES] moment.json: the last date %s is after T (%s)' % (dates[-1], T))
        ok = False
    for s in series:
        tag = 'moment.json %s' % s.get('as_of')
        env = _read_envelope(work, s.get('envelope'), s.get('envelope_sha256'), tag, T, P, code='[MOMENT-ENVELOPE]')
        if env is None:
            continue
        if text(env.get('T')) != text(s.get('as_of')):
            P.append('[MOMENT-ENVELOPE] %s: the call ran with T %s, not at the date of the point' % (tag, env.get('T')))
        gw = env.get('gateway') if isinstance(env.get('gateway'), dict) else {}
        if gw.get('index_total') != s.get('total'):
            P.append('[MOMENT-ENVELOPE] %s: total is %r but the gateway answer says index_total %r'
                     % (tag, s.get('total'), gw.get('index_total')))
    if series:
        check_matter_journal(work, T, P)
    if not ok:
        return
    th = {k: common.config()['moment'][k] for k in ('rise', 'revive_factor', 'trough_ratio', 'min_total')}
    if mo.get('thresholds') != th:
        P.append('[MOMENT-READING] moment.json: thresholds %r are not the ones of config.json moment (%r)' % (mo.get('thresholds'), th))
    per = matter.periods(series)
    got = [p for p in mo.get('periods') or [] if isinstance(p, dict)]
    same = len(per) == len(got) and all(
        a['from'] == b.get('from') and a['to'] == b.get('to') and a['count'] == b.get('count')
        and abs(a['per_year'] - (b.get('per_year') if isinstance(b.get('per_year'), (int, float)) else 1e9)) <= 0.01
        for a, b in zip(per, got))
    if not same:
        P.append('[MOMENT-READING] moment.json: periods are not the differences of the totals (recomputed: %s)'
                 % ', '.join('%s..%s=%s' % (p['from'], p['to'], p['count']) for p in per))
    reading = matter.moment_reading([p['per_year'] for p in per], th)
    if mo.get('reading') != reading:
        P.append('[MOMENT-READING] moment.json: reading is %r but the totals give %r (thresholds of config.json moment)'
                 % (mo.get('reading'), reading))
    if reading not in text(mo.get('line')):
        P.append('[MOMENT-READING] moment.json: the line must state the reading (%s)' % reading)


def check_report(work, P):
    rp = work / REPORT
    if not rp.exists():
        return
    try:
        import card
        expected = card.render(work, full=True)
    except Exception:                            # a broken input is reported by the other checks
        return
    if rp.read_text(encoding='utf-8') != expected:
        P.append('[REPORT-STALE] %s: it does not match the current files (an input changed, or it was edited by hand): run '
                 'tools/card.py again' % REPORT)


# ---------------------------------------------------------------- entry points


class _Self:
    """This module as an object, for tools/r3check.py (which must not import check back: it works however check was loaded)."""

    def __getattr__(self, name):
        return globals()[name]


def run_all(work, with_card=True):
    work = Path(work)
    P, W = [], []
    if not work.is_dir():
        return ['[MISSING] %s: not a directory' % work], []
    data, probs = load(work)
    P.extend(probs)
    mode = vp_mode(data)
    result = data.get('result.json')
    check_intake(data.get('intake.json'), P)
    check_vp_mode(data.get('intake.json'), P)
    check_prior_art(work, data.get('prior_art.json'), mode, P)
    ids = check_hypotheses(data.get('hypotheses.json'), P)
    executed = result if isinstance(result, dict) and result.get('mode') == 'executed' else None
    test_ids = check_tests(data.get('tests.json'), ids, executed, P, W)
    check_critique(work, data.get('critique.json'), mode, test_ids, P, W)
    check_result(result, test_ids, P)
    check_proof(work, result, data.get('tests.json'), P)
    check_reco(data.get('recommendation.json'), P)
    check_log(work, result, P)
    check_run_json(work, data, P)
    check_refs(work, data, P)
    check_rebound(work, data, mode, P, W)
    check_history(work, data, P, W)
    check_draft(work, data, mode, P)
    check_context(work, data, P, W)
    check_evidence(work, data, P, W)
    check_material(work, data, P, W)
    check_moment(work, data, P, W)
    r3check.run(work, data, P, W, _Self())
    v2check.run(work, data, P, W, _Self())
    import v3check
    v3check.run(work, data, P, W)
    v4check.run(work, data, P, W)
    W.extend(tournament.check_marks(work))
    if with_card:
        check_card(work, mode, P)
        check_report(work, P)
    if guards.is_v2(work):                        # v2: only factual, arithmetic, integrity and confidentiality errors block
        P, W = v2check.demote(P, W)
    return P, W


def problems(work):
    return run_all(work)[0]


def warnings(work):
    return run_all(work)[1]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dir')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    P, W = run_all(a.dir)
    if a.json:
        print(json.dumps({'note': NOTE, 'ok': not P, 'problems': P, 'warnings': W}, indent=2))
    else:
        print(NOTE)
        for p in P:
            print(p)
        for w in W:
            print(w if w.startswith('mark: ') else 'warning: ' + w)
        if not P:
            print('OK: %s' % Path(a.dir).resolve())
    return 1 if P else 0


if __name__ == '__main__':
    sys.exit(main())
