#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Mechanical check of the French court decisions cited in a text (an answer, a report) or in a JSON list of citations. No model.
Extraction (standard library, regular expressions):
  Cour de cassation appeal numbers   "24-15.143", "n° F 24-15.143", "pourvoi 24-15143"   -> number NN-NN.NNN
  court of appeal / tribunal docket  "RG 24/07526", "n° 24/07526"                         -> number NN/NNNNN
  ECLI                               "ECLI:FR:CCASS:2026:SO00225"
  for each one, from the words around it (the text since the previous citation, then a short stretch after it): the court
  (Cour de cassation and its chamber: soc, comm, civ1-3, cr, mi, pl; "cour d'appel de <city>" / "CA <city>"; tribunal judiciaire;
  tribunal de commerce) and the date ("18 mars 2026", "18/03/2026", "2026-03-18"). Flat JSON objects of the text (and a JSON input file:
  a list, or {"decisions": [...]} / {"citations": [...]}) are read field by field: juridiction|jurisdiction|court, date, numero|number,
  ecli, apport|claim. The claim of a citation is its JSON `apport`/`claim`, else the sentence that carries it.
Check of each distinct citation (number + date + court) through the gateway (tools/gateway.py, plugin law, engine judilibre, own call
pool `check_decisions`, date barrier T): search-judilibre on the number (court cc for an appeal number, else the court named, default ca),
first with the cited date as window for a docket number, then without; the records whose numbers (or ECLI) equal the cited one are the
candidates. Status:
  found        a candidate agrees on everything cited: date, kind of court, chamber (Cour de cassation), city (court of appeal)
  mismatch     the decision exists (same number, same court for a docket number) but the cited date, kind of court or chamber differs
               (`differences`, and the real values in `match`)
  not_found    no record with that number (a docket number found only at another court counts as absent: docket numbers are per court).
               Judilibre holds every Cour de cassation decision but not every court-of-appeal or tribunal decision: such a not_found carries
               `coverage: partial` and is a lead to check, not proof of invention
  not_checked  no PISTE credentials (engine skipped, 0 request), --offline, provider error, call cap, decision dated on/after T, or no
               number (`why` says which)
Support (optional, --support): the decision text (read judilibre:<id>) is searched for the quoted fragments of the claim ("...", «...»,
“...”, at least check_decisions.fragment_min_chars characters, whitespace, case and accents normalised): `supported` (all found),
`partial`, `not_supported` (none found; `undetermined` when the served text is cut), `undetermined` (no quoted fragment: the share of the
claim's content words present in the text is given as `word_overlap`, a pointer for a reader, never a verdict).
Never prints a key or a token (the gateway reads the PISTE pair by the key rule, KEYS.md). Never edits its input.
Usage: check_decisions.py INPUT|- [--T YYYY-MM-DD] [--state DIR] [--run NAME] [--plugin plugins/law.md] [--support] [--offline] [--out FILE] [--strict]
Output: JSON on stdout (or --out); exit code 0 = no not_found and no mismatch, 1 = at least one (with --strict also a not_checked), 2 = usage error.
Import: extract(text) -> [citation]; extract_json(obj) -> [citation]; check(citations, gateway=None, support=False, ...) -> dict."""
import argparse, datetime as dt, json, pathlib, re, sys, unicodedata

HERE = pathlib.Path(__file__).resolve().parent
CFG = json.loads((HERE / 'config.json').read_text())['check_decisions']
POOL = 'check_decisions'
STATUSES = ('found', 'mismatch', 'not_found', 'not_checked')

CASS_NUM = re.compile(r'(?<![\w/.-])(?:[A-Z]\s)?(\d{2})\s?[-‑.]\s?(\d{2})\s?\.?\s?(\d{3})(?![\w/-])')
RG_NUM = re.compile(r'(?<![\w/.-])(\d{2})\s?/\s?(\d{5})(?![\w/])')
ECLI = re.compile(r'\bECLI:FR:[A-Z]{2,8}:\d{4}:[A-Z0-9.]*[A-Z0-9]', re.I)
MONTHS = {'janvier': 1, 'fevrier': 2, 'mars': 3, 'avril': 4, 'mai': 5, 'juin': 6, 'juillet': 7, 'aout': 8, 'septembre': 9, 'octobre': 10,
          'novembre': 11, 'decembre': 12}
DATE_FR = re.compile(r'\b(\d{1,2})(?:er)?\s+(janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre)\s+(\d{4})\b', re.I)
DATE_NUM = re.compile(r'\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b')
DATE_ISO = re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b')
CHAMBERS = [('soc', r'\bsoc(?:iale|\.|\b)'), ('comm', r'\bcom(?:merciale\b|m?\.|m?\b)'), ('cr', r'\bcrim(?:inelle|\.|\b)'),
            ('civ1', r'\b(?:civ\.?\s?1|1(?:re|ère|ere|e)?\.?\s*(?:ch(?:ambre|\.)?\s*)?civ)'), ('civ2', r'\b(?:civ\.?\s?2|2(?:e|ème|eme|nde)?\.?\s*(?:ch(?:ambre|\.)?\s*)?civ)'),
            ('civ3', r'\b(?:civ\.?\s?3|3(?:e|ème|eme)?\.?\s*(?:ch(?:ambre|\.)?\s*)?civ)'),
            ('civ1', r'premi[èe]re chambre civile'), ('civ2', r'deuxi[èe]me chambre civile'), ('civ3', r'troisi[èe]me chambre civile'),
            ('pl', r'ass(?:\.|embl[ée]e)\s*pl[ée]n'), ('mi', r'ch(?:\.|ambre)\s*mixte')]
COURTS = [('cc', re.compile(r"cour de cassation|\bcass\b\.?|\bC\.\s?cass|\bcass\.", re.I)),
          ('ca', re.compile(r"(?i:cour d['’]appel)(?:\s+(?:de\s+|d['’]))?(?P<city>[A-ZÉÈÂÎa-zéèêàâîôûç' -]{2,40})?|\bCA\s+(?:de\s+|d['’])?(?P<city2>[A-ZÉ][\wéèêàâîôûç-]{2,30}(?:[ -][A-ZÉ][\wéèêàâîôûç-]+)?)")),
          ('tj', re.compile(r"tribunal judiciaire|\bTJ\b", re.I)), ('tcom', re.compile(r"tribunal de commerce|\bT\.?\s?com\b", re.I))]
QUOTE = re.compile(r'"([^"]{3,})"|«\s*([^»]{3,}?)\s*»|“([^”]{3,})”')
WORD = re.compile(r'[a-z]{5,}')
LINK = re.compile(r'\s*(?:[,;/]|\bet\b|\bou\b|\band\b|\bor\b)?\s*(?:n[°o]s?\.?|pourvois?)?\s*', re.I)   # between two numbers of one citation
SENT_END = re.compile(r'(?<=[.;!?])\s+(?=[A-ZÉÈÀ«"(])|\n')


def fold(s):
    """Lower case, accents removed, apostrophes and dashes unified, whitespace collapsed."""
    s = unicodedata.normalize('NFKD', str(s or '').replace('’', "'").replace('‑', '-').replace('–', '-'))
    return ' '.join(''.join(c for c in s if not unicodedata.combining(c)).lower().split())


def num_cass(s):
    m = CASS_NUM.search(str(s or ''))
    if m: return f'{m.group(1)}-{m.group(2)}.{m.group(3)}'
    m = re.fullmatch(r'\s*(?:[A-Z]\s?)?(\d{2})(\d{2})(\d{3})\s*', str(s or ''))           # bare 7 digits, only in a number field
    return f'{m.group(1)}-{m.group(2)}.{m.group(3)}' if m else None


def num_rg(s):
    m = RG_NUM.search(str(s or ''))
    return f'{m.group(1)}/{m.group(2)}' if m else None


def norm_number(s):
    """Any Judilibre number to the cited form (NN-NN.NNN or NN/NNNNN), else the folded string."""
    s = str(s or '').strip()
    return num_cass(s) or num_rg(s) or fold(s)


def parse_date(s):
    """First date of s -> 'YYYY-MM-DD' or None."""
    s = str(s or '')
    best = []
    for rx, kind in ((DATE_ISO, 'iso'), (DATE_FR, 'fr'), (DATE_NUM, 'num')):
        for m in rx.finditer(s):
            try:
                if kind == 'iso': d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                elif kind == 'fr': d = dt.date(int(m.group(3)), MONTHS[fold(m.group(2))], int(m.group(1)))
                else: d = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except (ValueError, KeyError): continue
            best.append((m.start(), d.isoformat()))
    return min(best)[1] if best else None


def dates_in(s):
    out = []
    for rx in (DATE_ISO, DATE_FR, DATE_NUM):
        for m in rx.finditer(s):
            d = parse_date(m.group(0))
            if d: out.append((m.start(), m.end(), d))
    return sorted(out)


def court_of(s, last=True):
    """(court key, chamber key, city) from the LAST (or first) court mention in s; (None, None, None) when none."""
    hits = []
    for k, rx in COURTS:
        for m in rx.finditer(s):
            city = None
            if k == 'ca':
                city = (m.group('city') or m.group('city2') or '').strip(" ,'")
                city = re.split(r"[,(;]|\s+(?:du|le|n°|no|rg|ch|chambre|p[ôo]le|\d)", city, maxsplit=1)[0].strip() or None
            hits.append((m.start(), m.end(), k, city))
    if not hits: return None, None, None
    p, e, k, city = max(hits) if last else min(hits)
    ch = None
    if k == 'cc':
        tail = s[p:p + CFG['chamber_window_chars']]          # the chamber is written right after the court ("Cass. soc.", "Cour de cassation, chambre sociale")
        f = fold(tail)
        found = [(m.start(), key) for key, rx in CHAMBERS for m in re.finditer(rx, f)]
        ch = min(found)[1] if found else None
    return k, ch, city


def _claim_sentence(text, a, b):
    starts = [m.end() for m in SENT_END.finditer(text, 0, a)]
    s = starts[-1] if starts else 0
    m = SENT_END.search(text, b)
    return text[s:m.start() if m else len(text)].strip()


def _citation(kind, number, date, court, chamber, city, claim, origin, context):
    return {'kind': kind, 'number': number, 'date': date, 'court': court, 'chamber': chamber, 'city': city,
            'claim': (claim or '').strip()[:1200], 'origin': origin, 'context': ' '.join(str(context or '').split())[:200]}


def from_fields(d, origin='json'):
    """A citation from a JSON object (French or English keys), or None when it carries no number nor ECLI."""
    if not isinstance(d, dict): return None
    g = lambda *ks: next((str(d[k]) for k in ks if d.get(k) not in (None, '')), '')
    jur, num, ecli = g('juridiction', 'jurisdiction', 'court'), g('numero', 'number', 'pourvoi', 'rg'), g('ecli')
    if not ecli: m = ECLI.search(num); ecli = m.group(0) if m else ''
    court, ch, city = court_of(jur, last=False)
    if ecli: kind, n = 'ecli', ecli.upper()
    elif court in ('ca', 'tj', 'tcom') and num_rg(num): kind, n = 'docket', num_rg(num)
    elif num_cass(num) and court in (None, 'cc'): kind, n, court = 'appeal', num_cass(num), 'cc'
    elif num_rg(num): kind, n = 'docket', num_rg(num)
    else: return None
    return _citation(kind, n, parse_date(g('date')), court, ch, city, g('apport', 'claim', 'holding', 'summary'), origin, f'{jur} {g("date")} {num}')


def _json_objects(text):
    """Flat JSON objects {...} of the text that parse and carry a number or an ECLI: (start, end, object)."""
    out = []
    for m in re.finditer(r'\{[^{}]*\}', text):
        try: o = json.loads(m.group(0))
        except ValueError: continue
        if isinstance(o, dict) and any(k in o for k in ('numero', 'number', 'ecli', 'pourvoi', 'rg')): out.append((m.start(), m.end(), o))
    return out


def extract(text):
    """Citations of a text: the JSON objects it holds, then the numbers written in prose (outside those objects)."""
    text = str(text or ''); out, masked = [], []
    for a, b, o in _json_objects(text):
        c = from_fields(o, 'text_json')
        if c: out.append(c); masked.append((a, b))
    hits = []
    for rx, kind in ((ECLI, 'ecli'), (CASS_NUM, 'appeal'), (RG_NUM, 'docket')):
        for m in rx.finditer(text):
            if any(a <= m.start() < b for a, b in masked) or any(a <= m.start() < b for a, b, *_ in hits): continue
            hits.append((m.start(), m.end(), kind, m.group(0)))
    hits.sort(); prev = 0
    for i, (a, b, kind, raw) in enumerate(hits):
        lo = max(prev, a - CFG['context_chars_before'], max((y for x, y in masked if y <= a), default=0))
        before = text[lo:a]
        nxt = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        after = text[b:min(nxt, b + CFG['context_chars_after'])]
        court, ch, city = court_of(before)
        ds = dates_in(before); d = ds[-1][2] if ds else None
        if i and court is None and d is None and LINK.fullmatch(before) and out and out[-1]['origin'] == 'text':
            p = out[-1]; court, ch, city, d = p['court'], p['chamber'], p['city'], p['date']      # "n° X et Y": Y shares X's court and date
        if court is None: court, ch, city = court_of(after, last=False)
        if d is None:
            da = dates_in(after); d = da[0][2] if da else None
        if kind == 'ecli':                           # the ECLI names its court: CCASS = Cour de cassation, CA.. = a court of appeal
            n = raw.upper(); court = 'cc' if ':CCASS:' in n else 'ca' if re.match(r'ECLI:FR:CA', n) else court
            ch, city = (ch, None) if court == 'cc' and court_of(before)[0] == 'cc' else (None, None)
        elif kind == 'appeal':                       # an appeal number NN-NN.NNN is a Cour de cassation number, whatever court is named nearby
            n = num_cass(raw)
            if court != 'cc':                        # "cassation of the judgment of the cour d'appel de X": the chamber of the last Cass mention
                cc = [m.start() for m in COURTS[0][1].finditer(before)]
                court, ch, city = ('cc',) + (court_of(before[cc[-1]:], last=False)[1:2] if cc else (None,)) + (None,)
        else: n = num_rg(raw); court = court if court in ('ca', 'tj', 'tcom') else 'ca'
        out.append(_citation(kind, n, d, court, ch if court == 'cc' else None, city, _claim_sentence(text, a, b), 'text', text[lo:b]))
        prev = b
    return merge(out)


def extract_json(obj):
    if isinstance(obj, dict): obj = obj.get('decisions') or obj.get('citations') or [obj]
    return merge([c for c in (from_fields(d) for d in obj if isinstance(obj, list)) if c])


def merge(cits):
    """One entry per (number, date, court, chamber, city); occurrences counted; the first claim kept, a JSON claim preferred."""
    seen = {}
    for c in cits:
        k = (c['kind'], c['number'], c['date'], c['court'], c['chamber'], fold(c['city']) if c['city'] else None)
        if k in seen:
            s = seen[k]; s['occurrences'] += 1
            if c['origin'] != 'text' and s['origin'] == 'text': s.update(claim=c['claim'], origin=c['origin'])
        else: seen[k] = dict(c, occurrences=1)
    return list(seen.values())


# ---------------------------------------------------------------- checking through the gateway
def _results(env):
    """(records list, why-not-checked or None) of a gateway envelope."""
    if not isinstance(env, dict): return None, 'provider_error'
    if env.get('refusal'): return None, 'cap_reached' if 'CAP' in str(env['refusal']) else 'refused: ' + str(env['refusal'])[:120]
    r = env.get('results')
    if isinstance(r, list): return r, None
    if isinstance(r, dict):
        if r.get('status') == 'skipped': return None, 'judilibre_' + str(r.get('reason') or 'skipped')
        return None, 'provider_error: ' + str(r.get('error') or r.get('refusal') or 'unexpected answer')[:160]
    return None, 'provider_error'


def _same(c, rec):
    if c['kind'] == 'ecli': return fold(rec.get('ecli')) == fold(c['number'])
    return any(norm_number(x) == c['number'] for x in (rec.get('numbers') or [rec.get('number')]) if x)


def _city_ok(c, rec):
    loc = fold(rec.get('location') or '')
    if not c.get('city') or not loc: return None
    city = fold(c['city']).replace(' ', '_').replace("'", '_').replace('-', '_')
    return city in loc.replace('-', '_') or loc.replace('ca_', '').replace('tj_', '') in city


def _diff(c, rec):
    d = []
    if c['date'] and rec.get('date') != c['date']: d.append('date')
    if c['court'] and rec.get('court') and rec['court'] != c['court']: d.append('court')
    if c['court'] == 'cc' and c['chamber'] and rec.get('chamber') and rec['chamber'] != c['chamber']: d.append('chamber')
    return d


def lookup(gw, c, n):
    """Judilibre records of the cited number -> (candidates, why-not-checked, calls made, excluded after T)."""
    court = 'cc' if c['kind'] == 'appeal' else (c['court'] if c['court'] in ('cc', 'ca', 'tj', 'tcom') else None)
    if c['kind'] == 'ecli': court = 'cc' if ':CCASS:' in c['number'] else 'ca' if ':CA' in c['number'] else court
    tries = []
    if c['kind'] == 'docket' and c['date']: tries.append({'date_from': c['date'], 'date_to': c['date']})
    tries.append({})
    calls, excluded, cands = 0, 0, []
    for opt in tries:
        o = dict(opt, **({'court': court} if court else {}))
        env = gw.call('search-judilibre', c['number'], n=n, **o); calls += 1
        recs, why = _results(env)
        if why: return [], why, calls, excluded
        excluded += int(env.get('excluded_post_T_or_forbidden') or 0)
        cands = [r for r in recs if _same(c, r)]
        if c['kind'] == 'docket' and c.get('city') and cands and not any(_city_ok(c, r) is not False for r in cands): continue
        if cands: break
    return cands, None, calls, excluded


def check_one(gw, c, n):
    out = dict(c)
    if not c.get('number'): return dict(out, status='not_checked', why='no_number')
    cands, why, calls, excl = lookup(gw, c, n)
    out['calls'] = calls
    if why: return dict(out, status='not_checked', why=why)
    if c['kind'] == 'docket' and c.get('city'):
        other = [r for r in cands if _city_ok(c, r) is False]
        cands = [r for r in cands if _city_ok(c, r) is not False]
        if other and not cands:
            out['same_number_elsewhere'] = [_m(r) for r in other[:5]]
    if not cands:
        if excl: return dict(out, status='not_checked', why='after_T_or_forbidden')
        partial = c['court'] in ('ca', 'tj', 'tcom') or c['kind'] == 'docket'
        return dict(out, status='not_found', why='absent_from_judilibre', **({'coverage': 'partial'} if partial else {}))
    best = min(cands, key=lambda r: len(_diff(c, r)))
    d = _diff(c, best)
    out['match'] = _m(best)
    if len(cands) > 1: out['other_matches'] = [_m(r) for r in cands if r is not best][:5]
    return dict(out, status='mismatch', differences=d, why='cited_' + '_'.join(d) + '_differs') if d else dict(out, status='found')


def _m(r): return {k: r.get(k) for k in ('id', 'date', 'court', 'chamber', 'location', 'number', 'ecli', 'title') if r.get(k)}


def fragments(claim):
    return [x for m in QUOTE.finditer(claim or '') for x in m.groups() if x and len(x.strip()) >= CFG['fragment_min_chars']]


def support(gw, c):
    """Quoted fragments of the claim searched in the decision text (read judilibre:<id>)."""
    env = gw.call('read', c['match']['id'])
    r = env.get('results') if isinstance(env, dict) else None
    if not isinstance(r, dict) or r.get('refusal') or r.get('status') == 'skipped' or not r.get('abstract'):
        return {'status': 'undetermined', 'why': 'text_not_read'}
    text = fold(r['abstract']); cut = 'whole' not in str(r.get('text_source') or '')
    fr = fragments(c['claim'])
    words = sorted(set(WORD.findall(fold(c['claim']))))
    ov = round(sum(w in text for w in words) / len(words), 2) if words else None
    if not fr: return {'status': 'undetermined', 'why': 'no_quoted_fragment', 'word_overlap': ov, 'text_cut': cut}
    ok = [f for f in fr if fold(f) in text]; miss = [f for f in fr if fold(f) not in text]
    st = 'supported' if not miss else 'partial' if ok else ('undetermined' if cut else 'not_supported')
    return {'status': st, 'fragments_found': ok, 'fragments_missing': miss, 'word_overlap': ov, 'text_cut': cut}


def default_gateway(T, state, run, plugins):
    sys.path.insert(0, str(HERE)); from gateway import Gateway
    return Gateway(plugins or [HERE.parent / 'plugins' / 'law.md'], T=T, run=run, state=state, pool=POOL)


def check(citations, gateway=None, support_check=False, offline=False, T=None, state=None, run='check-decisions', plugins=()):
    if not offline and gateway is None:
        T = T or (dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=1)).isoformat()
        gateway = default_gateway(T, state or 'vp-state', run, plugins)
    res = []
    for c in citations:
        if offline: r = dict(c, status='not_checked', why='offline')
        else:
            r = check_one(gateway, c, CFG['search_n'])
            if support_check and r.get('match') and r['status'] in ('found', 'mismatch'): r['support'] = support(gateway, r)
        res.append(r)
    summ = {s: sum(r['status'] == s for r in res) for s in STATUSES}
    if support_check: summ['support'] = {s: sum((r.get('support') or {}).get('status') == s for r in res) for s in ('supported', 'partial', 'not_supported', 'undetermined')}
    return {'tool': 'tools/check_decisions.py', 'T': T, 'source': 'Judilibre (PISTE) through the gateway', 'citations': res, 'summary': summ,
            'to_review': [f"{r['number']} ({r['date']}): {r['status']}" for r in res if r['status'] in ('not_found', 'mismatch')]}


def exit_code(rep, strict=False):
    s = rep['summary']
    return 1 if s['not_found'] or s['mismatch'] or (strict and s['not_checked']) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input', help='text file (answer, REPORT.md), JSON file of citations, or - for stdin')
    ap.add_argument('--T', help='date barrier of the gateway (decisions dated before T); default: tomorrow (UTC)')
    ap.add_argument('--state', default=None, help='gateway state directory (receipts, cache, token); default ./vp-state')
    ap.add_argument('--run', default='check-decisions'); ap.add_argument('--plugin', action='append', default=[])
    ap.add_argument('--support', action='store_true', help='read each decision found and look for the quoted fragments of its claim')
    ap.add_argument('--offline', action='store_true', help='no gateway call: extraction only, every citation not_checked')
    ap.add_argument('--out'); ap.add_argument('--strict', action='store_true', help='exit 1 also when a citation is not_checked')
    a = ap.parse_args(argv)
    if a.T:
        try: dt.date.fromisoformat(a.T)
        except ValueError: ap.error(f'--T: date YYYY-MM-DD expected: {a.T!r}')
    try: raw = sys.stdin.read() if a.input == '-' else pathlib.Path(a.input).read_text(encoding='utf-8', errors='replace')
    except OSError as e: print(f'cannot read {a.input}: {e.strerror}', file=sys.stderr); return 2
    try: cits = extract_json(json.loads(raw))
    except ValueError: cits = extract(raw)
    rep = check(cits, support_check=a.support, offline=a.offline, T=a.T, state=a.state, run=a.run, plugins=a.plugin)
    s = json.dumps(rep, ensure_ascii=False, indent=1)
    if a.out: pathlib.Path(a.out).write_text(s, encoding='utf-8'); print(json.dumps(dict(rep['summary'], out=a.out), ensure_ascii=False))
    else: print(s)
    return exit_code(rep, a.strict)


if __name__ == '__main__':
    sys.exit(main())
