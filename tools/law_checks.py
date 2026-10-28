#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Mechanical legal checks after the level-1 verification (plugins/law.md, section "Verification rules"). No model, standard library,
offline by default. They only tighten: the final status of a claim is the strictest of the verifier's status and of the rules.
Usage: law_checks.py DIR [--as-of YYYY-MM-DD] [--order EU|COE|FR|FR-ADM|FR-JUD|...] [--comparative] [--today YYYY-MM-DD] [--out FILE]
                         [--fetch [--plugin plugins/law.md] [--T YYYY-MM-DD] [--state DIR] [--run NAME]]
Input: DIR/card.json (claims[].source.key, optional source.keys = further anchors; card.sources[key] = {celex|ecli|ja|hal|thesesfr|id, ...}),
DIR/verdicts.json, the saved records: DIR/sources/<key>/record.json (gateway `read` answer, written by verifier.py or by --fetch), else
DIR/sources/<key>/source.txt when it holds the gateway JSON (injected mode), else the fields copied into card.sources[key] (origin "card").
Question date: claim `as_of` > card `as_of`/`question_date` > scope.md line `as of|question date|date of the question: YYYY-MM-DD` > --as-of
> T of state/journal.jsonl (origin stated). Legal order: claim `order` > card `order`/`jurisdiction` > scope.md line `order|legal order:` > --order.
Rules (result supported | needs_confirmation | unsupported, with the observable trigger; missing data -> needs_confirmation, never a pass):
  resolves (law.fabricated_citation; rule 7)   official_text (law.non_binding; rule 6)   in_force_at_date, version_pinned (law.not_in_force; 1-2)
  jurisdiction_match (law.wrong_jurisdiction; 3)   not_overturned (law.overruled; 4)   source_tier (law.doctrine_for_primary; 5)
  coverage (negative claims, law.misgrounded; 8)   bounded_total (false totals, null literals, law.misgrounded; 9)
Mapping of an `unsupported` rule to a level-1 status (MAP): resolves, jurisdiction_match -> ABSENT; official_text -> SOURCE-UNAVAILABLE;
the others -> DISTORTED (the trigger is the discrepancy that says what to write). needs_confirmation -> status kept, claim listed in to_flag.
Output: DIR/law_checks.json; never edits REPORT.md, card.json nor verdicts.json (the orchestrator applies it, SKILL.md section 7).
Import: check_run(dir, ...) -> dict; check_claim(claim, anchors, ctx) -> list of rule outcomes."""
import argparse, datetime as dt, json, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
RESULTS = ('unsupported', 'needs_confirmation', 'supported')                     # strictest first
RANK = {r: i for i, r in enumerate(RESULTS)}
STATUS_RANK = {'FOUND': 0, 'UNVERIFIED': 1, 'SOURCE-UNAVAILABLE': 1, 'DISTORTED': 2, 'ABSENT': 3, 'INVALID': 3}
BIAS = {'resolves': 'law.fabricated_citation', 'official_text': 'law.non_binding', 'in_force_at_date': 'law.not_in_force',
        'version_pinned': 'law.not_in_force', 'jurisdiction_match': 'law.wrong_jurisdiction', 'not_overturned': 'law.overruled',
        'source_tier': 'law.doctrine_for_primary', 'coverage': 'law.misgrounded', 'bounded_total': 'law.misgrounded'}
MAP = {'resolves': 'ABSENT', 'jurisdiction_match': 'ABSENT', 'official_text': 'SOURCE-UNAVAILABLE'}   # others: DISTORTED
ALSO_BINDING = {'FR': ['EU', 'COE'], 'EU': ['COE']}                               # law.md rule 3
FINAL_COURTS = ('CJ', 'CO', 'CE', 'cc')                                           # law.md rule 4 (CJEU judgments and orders, Conseil d'Etat, Cour de cassation)
TIER = {'primary': 3, 'secondary': 2, 'grey': 1}
SKIP_TIERS = ('secondary', 'grey')                                                # doctrine exempt from jurisdiction_match, a primary source never
OPEN_END_YEAR = 2999                                                              # Cellar 9999-12-31, LEGI 2999-01-01 = no end
NULLS = ('', 'undefined', 'null', 'none_literal')                                 # null literals removed (rule 9); 'none' is a value (history checked)
LEGI_DEAD = ('MODIFIE_MORT_NE',)                                                  # never in force
LEGI_STATES = ('VIGUEUR', 'ABROGE', 'MODIFIE', 'VIGUEUR_DIFF', 'ABROGE_DIFF', 'MODIFIE_MORT_NE', 'TRANSFERE')
JA_COVERAGE = {'CE': '2021-09-30', 'CAA': '2022-03-31', 'TA': '2022-06-30'}       # law.md 4, same as the gateway
LAW_PREFIX = ('celex', 'ecli', 'ja', 'hal', 'thesesfr')
FORMS = {'celex': r'[0-9CE]\d{4}[A-Z]{1,3}\d{1,5}[0-9A-Z()_.\-]*', 'ecli': r'ECLI:[A-Z]{2}:[A-Z0-9.]{1,7}:\d{4}:[A-Z0-9.]{1,25}',
         'ja': r'[A-Z]{2,3}\d{0,3}/[A-Z]{2,5}_[A-Za-z0-9]+_\d{8}', 'hal': r'[a-z]+-\d+', 'thesesfr': r'[0-9]{4}[A-Z0-9]{4,12}'}
UNRESOLVED = re.compile(r'^\s*(not found|malformed|expected form|not an administrative-court ECLI)', re.I)
NEGATIVE = re.compile(r"\b(no|none|never|aucune?|jamais)\b[^.]{0,40}\b(decisions?|rulings?|judgments?|judgements?|cases?|arr[eê]ts?|d[eé]cisions?)\b", re.I)
COMPLETE = re.compile(r'\b(all|every|complete|exhaustive|in total|a total of|the total|toutes?|tous|exhaustif|au total)\b', re.I)
AT_LEAST = re.compile(r'\b(at least|au moins|bounded|capped|or more)\b', re.I)
NOT_OFFICIAL = re.compile(r'(_RES|_INF)\b|(?:^|[:\s])6\d{4}CC|press[ _-]?release|communiqu[eé]|/cp\d{4,}|\bcp\d{6}', re.I)


def day(x):
    """YYYY-MM-DD (or a longer ISO string) -> date; anything else -> None (never guessed)."""
    if not isinstance(x, str) or len(x) < 10: return None
    try: return dt.date.fromisoformat(x[:10])
    except ValueError: return None


def val(rec, k):
    v = rec.get(k)
    return None if isinstance(v, str) and v.strip().lower() in NULLS else v


def ident_of(key, desc):
    """Law identifier of a card source: `<prefix>:<value>` (celex, ecli, ja, hal, thesesfr), from desc or from the key itself; else None."""
    for c in (desc.get('id'), key):
        if isinstance(c, str) and c.split(':', 1)[0].lower() in LAW_PREFIX and ':' in c: p, _, v = c.partition(':'); return f'{p.lower()}:{v.strip()}'
    for p in LAW_PREFIX + ('nnt',):
        if desc.get(p): return f"{'thesesfr' if p == 'nnt' else p}:{str(desc[p]).strip()}"
    return None


def well_formed(ident):
    p, _, v = ident.partition(':')
    if p == 'ecli' and not v.upper().startswith('ECLI:'): v = 'ECLI:' + v
    return bool(re.fullmatch(FORMS[p], v))


def parse_record(text):
    """Gateway `read` answer (envelope {"results": {...}} or bare record) -> (record dict | None, refusal | None, error | None)."""
    try: x = json.loads(text) if isinstance(text, str) else text
    except ValueError: return None, None, None
    if not isinstance(x, dict): return None, None, None
    r = x.get('results', x) if isinstance(x.get('results', x), dict) else {}
    if x.get('refusal') or r.get('refusal'): return None, x.get('refusal') or r.get('refusal'), None
    if x.get('error') or r.get('error'): return None, None, x.get('error') or r.get('error')
    return (r, None, None) if r.get('id') or r.get('celex') or r.get('tier') else (None, None, None)


def load_anchor(d, key, desc, ident):
    """-> anchor dict: key, ident, rec (fields), origin record|source|card|none, refusal, error."""
    from_fs = re.sub(r'[^\w.-]+', '_', str(key)).strip('.') or 'source'          # same as verifier.fs_key
    for name, origin in (('record.json', 'record'), ('source.txt', 'source')):
        f = pathlib.Path(d) / 'sources' / from_fs / name
        if f.is_file():
            rec, ref, err = parse_record(f.read_text(encoding='utf-8', errors='replace'))
            if rec or ref or err: return {'key': key, 'ident': ident, 'rec': {**desc, **rec} if rec else dict(desc), 'origin': origin if rec else 'none', 'refusal': ref, 'error': err}
    fields = {k for k in desc if k not in ('title', 'id', 'url')}
    return {'key': key, 'ident': ident, 'rec': dict(desc), 'origin': 'card' if fields - set(LAW_PREFIX) else 'none', 'refusal': None, 'error': None}


def kind_of(a):
    """text | decision | doctrine | None, from the record (type, CELEX sector, tier)."""
    r = a['rec']; t = str(val(r, 'type') or '').lower(); c = celex_of(a)
    if r.get('tier') in SKIP_TIERS or t in ('thesis', 'doctrine', 'art', 'article', 'ouv', 'couv'): return 'doctrine'
    if t == 'decision' or c[:1] == '6' or (a['ident'] or '').startswith(('ja:', 'ecli:')): return 'decision'
    if t == 'text' or c[:1] in ('0', '3') or val(r, 'in_force_from') or val(r, 'valid_from') or val(r, 'legi_state'): return 'text'
    return None


def celex_of(a):
    i = a['ident'] or ''
    return str(val(a['rec'], 'celex') or (i.partition(':')[2] if i.startswith('celex:') else ''))


def ancestors(code): parts = str(code).split('-'); return ['-'.join(parts[:i]) for i in range(1, len(parts) + 1)]


def out(rule, result, trigger, a=None): return {'rule': rule, 'anchor': a['key'] if a else None, 'result': result, 'trigger': trigger, 'bias': BIAS[rule]}


# ---------------------------------------------------------------- rules on one anchored record

def r_resolves(a, ctx):
    i = a['ident']
    if i is None: return None
    if not well_formed(i): return out('resolves', 'unsupported', f'{i}: malformed reference, does not resolve', a)
    if a['refusal'] and UNRESOLVED.match(str(a['refusal'])): return out('resolves', 'unsupported', f'{i}: gateway answers "{a["refusal"]}"', a)
    vs = ctx.get('verifier_discrepancy') or ''
    if UNRESOLVED.match(vs): return out('resolves', 'unsupported', f'{i}: verifier read "{vs}"', a)
    if a['refusal']: return out('resolves', 'needs_confirmation', f'{i}: refused by the gateway ("{a["refusal"]}"), existence not shown', a)
    if a['error']: return out('resolves', 'needs_confirmation', f'{i}: provider error on reading ({str(a["error"])[:80]})', a)
    if a['origin'] in ('record', 'source'): return out('resolves', 'supported', f'{i}: record read through the gateway', a)
    return out('resolves', 'needs_confirmation', f'{i}: not resolved offline (no saved record; run with --fetch)', a)


def r_official(a, ctx):
    r = a['rec']; probe = ' '.join(str(x) for x in (a['ident'], val(r, 'celex'), val(r, 'url'), val(r, 'type'), val(r, 'text_source')) if x)
    if NOT_OFFICIAL.search(probe) or str(val(r, 'type') or '').lower() in ('press_release', 'summary', 'ag_opinion'):
        return out('official_text', 'unsupported', f'cited text is not the official text ({probe[:120]}): _RES/_INF summary, press release or Advocate General opinion', a)
    return None


def flag_contradicts(r, start, end, today):
    f = str(val(r, 'in_force') if val(r, 'in_force') is not None else '').strip().lower()
    if f not in ('0', '1', 'true', 'false'): return None
    now = start <= today and (end is None or today <= end)
    if now != (f in ('1', 'true')):
        return f"inconsistent record: in-force flag {f} but its dates say {'in force' if now else 'not in force'} on {today}"
    return None


def r_in_force(a, ctx):
    k = kind_of(a); r = a['rec']; as_of = ctx['as_of']
    if k not in ('text', 'decision'): return None
    if as_of is None: return out('in_force_at_date', 'needs_confirmation', 'date of the question unknown or malformed', a)
    if k == 'decision':
        d = day(val(r, 'date'))
        if d is None: return out('in_force_at_date', 'needs_confirmation', 'date of the decision missing or malformed', a)
        if d > as_of: return out('in_force_at_date', 'unsupported', f'decision of {d}, later than the date of the question {as_of}', a)
        return out('in_force_at_date', 'supported', f'decision of {d}, before {as_of}', a)
    start = day(val(r, 'in_force_from') or val(r, 'valid_from'))
    if start is None: return out('in_force_at_date', 'needs_confirmation', 'validity start missing or malformed', a)
    state = str(val(r, 'legi_state') or '').upper()
    if state in LEGI_DEAD: return out('in_force_at_date', 'unsupported', f'LEGI state {state}: version never in force', a)
    if state and state not in LEGI_STATES: return out('in_force_at_date', 'needs_confirmation', f'LEGI state {state} outside the closed mapping', a)
    masked = 'masked' in str(val(r, 'validity') or '')
    ends = []                                                                   # (field, end date or None, inclusive)
    for f, inc in (('in_force_to', True), ('valid_until', False)):
        if f in r or (f == 'in_force_to' and 'valid_until' not in r):
            raw = val(r, f); e = day(raw)
            if raw is not None and e is None: return out('in_force_at_date', 'needs_confirmation', f'{f} malformed ({raw!r})', a)
            ends.append((f, e, inc))
    last = None
    for f, e, inc in ends:
        if e is not None and e.year < OPEN_END_YEAR: last = e if inc else e - dt.timedelta(days=1)
    if (why := flag_contradicts(r, start, last, ctx['today'])) is not None: return out('in_force_at_date', 'needs_confirmation', why, a)
    if as_of < start: return out('in_force_at_date', 'unsupported', f'not yet in force on {as_of} (from {start})', a)
    for f, e, inc in ends:
        if e is None:
            if masked and ctx.get('T') and (as_of < ctx['T'] or inc and as_of == ctx['T']): continue   # gateway: an end on/after T is masked
            return out('in_force_at_date', 'needs_confirmation', f'{f} missing: end of validity unknown', a)
        if e.year < OPEN_END_YEAR and (as_of > e if inc else as_of >= e):
            return out('in_force_at_date', 'unsupported', f"no longer in force on {as_of} (end {e}, {'inclusive' if inc else 'exclusive'})", a)
    if 'applies_from' in r or masked:
        ap = day(val(r, 'applies_from'))
        if ap is None: return out('in_force_at_date', 'needs_confirmation', 'date of application missing (or masked: on/after T)', a)
        if as_of < ap: return out('in_force_at_date', 'needs_confirmation', f'in force since {start} but applicable only from {ap}', a)
    return out('in_force_at_date', 'supported', f'in force and applicable on {as_of} (from {start})', a)


def r_version(a, ctx):
    if kind_of(a) != 'text': return None
    r = a['rec']; c = celex_of(a); v = val(r, 'version')
    if c[:1] == '0':                                                            # consolidated version: CELEX 0YYYY...-YYYYMMDD
        m = re.search(r'-(\d{8})$', c)
        if not m: return out('version_pinned', 'needs_confirmation', f'consolidated CELEX {c} without its version date', a)
        vd = dt.date(int(m[1][:4]), int(m[1][4:6]), int(m[1][6:]))
        if ctx['as_of'] and vd > ctx['as_of']: return out('version_pinned', 'unsupported', f'consolidated version of {vd}, later than the date of the question {ctx["as_of"]}', a)
        return out('version_pinned', 'supported', f'version {c}', a)
    if c or v: return out('version_pinned', 'supported', f'version {c or v}', a)
    return out('version_pinned', 'needs_confirmation', 'no exact version named (CELEX or version)', a)


def r_jurisdiction(a, ctx):
    r = a['rec']
    if r.get('tier') in SKIP_TIERS or kind_of(a) == 'doctrine': return None
    if ctx.get('comparative'): return out('jurisdiction_match', 'supported', 'comparative question', a)
    asked, src = ctx.get('order'), val(r, 'order') or val(r, 'jurisdiction')
    if not asked: return out('jurisdiction_match', 'needs_confirmation', 'legal order of the question unknown', a)
    if not src: return out('jurisdiction_match', 'needs_confirmation', 'legal order of the source unknown', a)
    if src == asked or asked in ancestors(src) or src in ancestors(asked): return out('jurisdiction_match', 'supported', f'{src} within {asked}', a)
    for code in ancestors(asked):
        if any(src == b or b in ancestors(src) for b in ALSO_BINDING.get(code, [])):
            return out('jurisdiction_match', 'needs_confirmation', f'{src} binds {asked} only through its own mechanism (direct effect, transposition)', a)
    if src.split('-')[0] == asked.split('-')[0]: return out('jurisdiction_match', 'needs_confirmation', f'{src} is another court order than {asked}: persuasive at most', a)
    return out('jurisdiction_match', 'unsupported', f'{src} is not the legal order of the question ({asked})', a)


def r_overturned(a, ctx):
    k = kind_of(a); r = a['rec']
    if k not in ('text', 'decision'): return None
    hist = [h for h in (r.get('set_aside_by'), r.get('declared_void_by')) if h is not None]
    dated = {x.get('celex'): day(x.get('date')) for x in r.get('declared_void_by') or [] if isinstance(x, dict)}
    by, later = [], []
    for h in hist:
        for x in (h if isinstance(h, list) else [h]):
            x = x.get('celex') if isinstance(x, dict) else x
            if not x or str(x).strip().lower() in NULLS + ('none',): continue
            (later if ctx['as_of'] and dated.get(x) and dated[x] > ctx['as_of'] else by).append(str(x))   # set aside after the question date
    if later and not by:
        return out('not_overturned', 'supported', f"good law on {ctx['as_of']}: set aside later, by {', '.join(sorted(set(later)))}", a)
    if by: return out('not_overturned', 'unsupported', f"set aside, reversed or declared void by {', '.join(sorted(set(by)))}", a)
    court = val(r, 'court') or val(r, 'court_code') or val(r, 'jurisdiction_code')
    if k == 'decision' and court in FINAL_COURTS: return out('not_overturned', 'supported', f'{court} decides in last resort', a)
    if hist: return out('not_overturned', 'supported', 'subsequent history checked: nothing found before T', a)
    return out('not_overturned', 'needs_confirmation', f"subsequent history unknown ({court or 'court unknown'}, no citator for this source)", a)


PER_ANCHOR = (r_resolves, r_official, r_in_force, r_version, r_jurisdiction, r_overturned)


# ---------------------------------------------------------------- rules on the claim

def r_tier(claim, anchors):
    if claim.get('decisive') is False: return None
    ranks = [TIER[a['rec'].get('tier')] for a in anchors if a['rec'].get('tier') in TIER]
    if not ranks: return out('source_tier', 'needs_confirmation', 'no anchor declares its tier')
    if max(ranks) >= TIER['primary']: return out('source_tier', 'supported', 'rests on a primary source')
    return out('source_tier', 'needs_confirmation', 'only doctrine (secondary or grey sources): find the primary text')


def coverage_of(anchors, claim):
    if day(claim.get('coverage_from')): return day(claim['coverage_from'])
    cs = [day(val(a['rec'], 'coverage_from')) for a in anchors]
    cs += [day(next((v for k, v in JA_COVERAGE.items() if str(val(a['rec'], 'court') or '').startswith(k)), None)) for a in anchors if (a['ident'] or '').startswith('ja:')]
    cs = [c for c in cs if c]
    if cs: return max(cs)
    return day(JA_COVERAGE['TA']) if claim.get('engine') == 'justice-administrative' else None   # court unknown: latest opening


def r_coverage(claim, anchors):
    if not (claim.get('negative') or NEGATIVE.search(str(claim.get('text') or ''))): return None
    if 'COE' in {val(a['rec'], 'order') for a in anchors} or claim.get('order') == 'COE' or claim.get('engine') == 'hudoc':
        return out('coverage', 'needs_confirmation', 'negative claim on the ECHR: HUDOC not served, absence not observable')
    rc = str(claim.get('receipt') or '')
    if not (re.search(r'\d{3,}', rc) or re.search(r'"[^"]{3,}"', rc)):
        return out('coverage', 'needs_confirmation', 'negative claim without the receipt of a query by number or exact phrase')
    w, cov = day(claim.get('window_from')), coverage_of(anchors, claim)
    if w is None: return out('coverage', 'needs_confirmation', 'negative claim without the start of the period it covers (window_from)')
    if cov and w < cov: return out('coverage', 'needs_confirmation', f'negative claim from {w}, before the coverage of the source (from {cov}): absence proves nothing')
    return out('coverage', 'supported', f'negative claim within the coverage window (from {cov or "the start of the source"}), receipt {rc[:60]!r}')


def r_bounded(claim, anchors):
    if not claim.get('total'): return None
    status = str(claim.get('total_status') or 'bounded').lower()               # every law engine reports `bounded`
    t = str(claim.get('text') or '')
    if status != 'bounded' and status != 'complete': return out('bounded_total', 'needs_confirmation', f'total status {status!r} unknown')
    if status == 'complete' and not claim.get('receipt'): return out('bounded_total', 'needs_confirmation', 'total said complete without its receipt')
    if status == 'complete' or AT_LEAST.search(t): return out('bounded_total', 'supported', f'total stated as {"complete (receipt)" if status == "complete" else "a lower bound"}')
    if COMPLETE.search(t): return out('bounded_total', 'unsupported', 'total presented as complete while the provider total is bounded (capped at 1,000, partial pages): write "at least N"')
    return out('bounded_total', 'needs_confirmation', 'count from a bounded total: say "at least N"')


def check_claim(claim, anchors, ctx):
    """All applicable rules for one claim -> list of outcomes (each: rule, anchor, result, trigger, bias)."""
    o = []
    for a in anchors:
        for f in PER_ANCHOR:
            x = f(a, ctx)
            if x: o.append(x)
    for f in (r_tier, r_coverage, r_bounded):
        x = f(claim, anchors)
        if x: o.append(x)
    return o


def law_status(outcomes):
    """Worst rule result -> level-1 status it maps to (None: nothing stricter than FOUND) and the outcome that drives it."""
    bad = [x for x in outcomes if x['result'] == 'unsupported']
    if not bad: return None, None
    worst = max(bad, key=lambda x: STATUS_RANK[MAP.get(x['rule'], 'DISTORTED')])
    return MAP.get(worst['rule'], 'DISTORTED'), worst


# ---------------------------------------------------------------- run directory

def read_json(p):
    try: return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError): return None


def scope_value(d, names):
    f = pathlib.Path(d) / 'scope.md'
    if not f.is_file(): return None
    m = re.search(r'^[\s*#>-]*(?:%s)\s*[:=]\s*`?([A-Za-z0-9-]+)' % '|'.join(names), f.read_text(encoding='utf-8', errors='replace'), re.I | re.M)
    return m.group(1) if m else None


def journal_T(d):
    j = pathlib.Path(d) / 'state' / 'journal.jsonl'
    ts = sorted({json.loads(l).get('T') for l in j.read_text(encoding='utf-8').splitlines() if l.strip()} - {None}) if j.is_file() else []
    return ts[0] if len(ts) == 1 else None


def context(d, card, as_of=None, order=None, comparative=False, today=None, T=None):
    sd, so = scope_value(d, ['as of', 'question date', 'date of the question']), scope_value(d, ['legal order', 'order'])
    jt = T or journal_T(d)
    date, origin = next(((v, o) for v, o in ((card.get('as_of') or card.get('question_date'), 'card'), (sd, 'scope.md'), (as_of, '--as-of'),
                                                (jt, 'T (journal or --T)')) if v), (None, 'unknown'))
    od, oo = next(((v, o) for v, o in ((card.get('order') or card.get('jurisdiction'), 'card'), (so, 'scope.md'), (order, '--order')) if v), (None, 'unknown'))
    return {'as_of': day(date), 'as_of_origin': origin, 'order': od.upper() if od else None, 'order_origin': oo,
            'comparative': bool(comparative or card.get('comparative')), 'today': day(today) or dt.datetime.now(dt.timezone.utc).date(), 'T': day(jt)}


def fetch_records(d, anchors, plugins, T, state, run):
    """--fetch: read through the gateway (date barrier T) the anchors without a saved record; the answer is saved as record.json."""
    sys.path.insert(0, str(HERE)); from gateway import Gateway
    g = Gateway(plugins, T=T, run=run, state=state)
    for a in anchors:
        if a['ident'] and a['origin'] in ('card', 'none') and not a['refusal'] and well_formed(a['ident']):
            rep = g.read(a['ident'])
            f = pathlib.Path(d) / 'sources' / (re.sub(r'[^\w.-]+', '_', str(a['key'])).strip('.') or 'source') / 'record.json'
            f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding='utf-8')


def check_run(d, as_of=None, order=None, comparative=False, today=None, fetch=False, plugins=(), T=None, state=None, run='law-checks'):
    d = pathlib.Path(d); card = read_json(d / 'card.json')
    if not isinstance(card, dict): raise ValueError('card.json missing or unreadable')
    ver = read_json(d / 'verdicts.json') or {}
    vs = {v.get('id'): v for v in (ver.get('claims') or []) if isinstance(v, dict)}
    table = card.get('sources') or {}
    ctx0 = context(d, card, as_of, order, comparative, today, T)

    def anchors_of(c):
        s = c.get('source') or {}; keys = [s.get('key')] + list(s.get('keys') or [])
        return [load_anchor(d, k, table.get(k) or {}, ident_of(k, table.get(k) or {})) for k in dict.fromkeys(k for k in keys if k)]
    if fetch:
        fetch_records(d, [a for c in card.get('claims') or [] for a in anchors_of(c)], plugins or [HERE.parent / 'plugins' / 'law.md'],
                      T or (ctx0['T'] and ctx0['T'].isoformat()), state or d / 'state', run)
    claims, skipped = [], []
    for c in card.get('claims') or []:
        an = anchors_of(c)
        if not any(a['ident'] or a['rec'].get('tier') or a['rec'].get('order') for a in an): skipped.append(c.get('id')); continue
        v = vs.get(c.get('id')) or {}
        ctx = dict(ctx0, verifier_discrepancy=str(v.get('discrepancy') or '') if v.get('status') == 'SOURCE-UNAVAILABLE' else '')
        if c.get('as_of'): ctx['as_of'] = day(c['as_of'])
        if c.get('order'): ctx['order'] = c['order']
        o = check_claim(c, an, ctx)
        mapped, worst = law_status(o)
        st = v.get('status')
        final = mapped if mapped and STATUS_RANK[mapped] > STATUS_RANK.get(st, -1) else st
        nc = [x for x in o if x['result'] == 'needs_confirmation']
        claims.append({'id': c.get('id'), 'as_of': ctx['as_of'] and ctx['as_of'].isoformat(), 'order': ctx['order'],
                       'anchors': [{'key': a['key'], 'ident': a['ident'], 'record_origin': a['origin']} for a in an], 'rules': o,
                       'catalogue': sorted({x['bias'] for x in o if x['result'] != 'supported'}),
                       'law_result': min((x['result'] for x in o), key=RANK.get, default='supported'),
                       'verifier_status': st, 'final_status': final, 'changed': final != st,
                       'discrepancy': f"law_checks {worst['rule']}: {worst['trigger']}" if final != st and worst else '', 'flagged': bool(nc),
                       'to_confirm': [f"{x['rule']}: {x['trigger']}" for x in nc]})
    return {'tool': 'tools/law_checks.py', 'card_id': card.get('card_id'), 'as_of': ctx0['as_of'] and ctx0['as_of'].isoformat(), 'as_of_origin': ctx0['as_of_origin'],
            'order': ctx0['order'], 'order_origin': ctx0['order_origin'], 'comparative': ctx0['comparative'], 'today': ctx0['today'].isoformat(),
            'mapping': {'unsupported': {r: MAP.get(r, 'DISTORTED') for r in BIAS}, 'needs_confirmation': 'status kept, claim flagged (to_flag)',
                        'final': 'strictest of verifier status and mapped status (FOUND < UNVERIFIED = SOURCE-UNAVAILABLE < DISTORTED < ABSENT = INVALID)'},
            'claims': claims, 'not_law': skipped, 'to_apply': [c['id'] for c in claims if c['changed']], 'to_flag': [c['id'] for c in claims if c['flagged']],
            'summary': {'claims': len(claims), 'changed': sum(c['changed'] for c in claims), 'flagged': sum(c['flagged'] for c in claims), 'final': {s: sum(c['final_status'] == s for c in claims) for s in STATUS_RANK},
                        'catalogue': sorted({b for c in claims for b in c['catalogue']})}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dir'); ap.add_argument('--as-of'); ap.add_argument('--order'); ap.add_argument('--comparative', action='store_true')
    ap.add_argument('--today', help='dates the sources\' own in-force flags (default: current UTC date)'); ap.add_argument('--out')
    ap.add_argument('--fetch', action='store_true', help='re-read through the gateway the records missing from sources/ (date barrier T)')
    ap.add_argument('--plugin', action='append', default=[]); ap.add_argument('--T'); ap.add_argument('--state'); ap.add_argument('--run', default='law-checks')
    a = ap.parse_args()
    for x in (a.as_of, a.today, a.T):
        if x and not day(x): ap.error(f'date expected as YYYY-MM-DD: {x!r}')
    try: res = check_run(a.dir, a.as_of, a.order, a.comparative, a.today, a.fetch, a.plugin, a.T, a.state, a.run)
    except ValueError as e: print(str(e)); sys.exit(2)
    p = pathlib.Path(a.out or pathlib.Path(a.dir) / 'law_checks.json'); p.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(dict(res['summary'], to_apply=res['to_apply'], to_flag=res['to_flag'], out=str(p)), ensure_ascii=False))


if __name__ == '__main__':
    main()
