#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Mechanical aid of the hybrid free-draft step of Frontier (SKILL.md step 0-ter). Offline, no model, standard library.

The host writes, without any format, what it knows (close works, hypotheses, tests, orders of magnitude, neighbouring
ideas) in <dir>/free_draft.md. Then every claim and reference of that draft that the card takes up is either VERIFIED
(a VP reference), or marked "unverified (memory)", or removed: draft_claims.json lists them, tools/check.py enforces it
([DRAFT-*]). This tool finds, mechanically, what in the draft looks like a claim to be settled, and writes a starting
list. It never decides: statuses are the host's.

In v2, full prose claims form the inventory. The host MUST submit the five
decision priorities (all if fewer) with `submit`, then run VP verification and
inspect their verdicts. Other leads stay unverified (memory), including ideas
that contain numbers. Only normalized duplicate leads count once.

What it detects (a net, not a proof; a claim it cannot see is still the host's duty):
  reference   author-year: "Gu, Kelly, Xiu (2020, RFS)", "Grinsztajn et al. (2022)", "(Smith et al., 2019)"
  identifier  doi:10.xxxx/..., arxiv:2101.00001, pmid:123456
  number      a decimal number or a percentage ("1,82", "0.27", "12.5%")
A detected item is "taken up" when a text field of prior_art, hypotheses, tests, recommendation, result, rebound files,
evidence_table, material or moment holds it: a reference when the same first surname and year are in one string, an
identifier when the same identifier is, a number when the same number is in a string that shares two content words with
the draft sentence of that number. An identifier that appears only as the "id" of a VP reference object ({id, run, claim})
is not counted: VP verifies it (without VP the header of the card says that no reference is verified).
In strict analysis, numeric cues are grouped into complete prose items, including
short label/value claims. Only a whole quote establishes exact textual reuse.
A shared numeric value and content word, or a shared reference/identifier, can
suggest possible reuse; these partial matches require human verification and
never inherit verification from the source quote. This net is not semantic verification.

Subcommands (DIR = the Frontier working directory):
  scan DIR [--json]   list the detected items, the claims of draft_claims.json that cover each (their quote holds the
                      item), and where each is taken up (file, path, marked or not).
  stub DIR            write draft_claims.json with one "unverified_memory" claim per detected item (and the SHA-256 of the
                      draft); refuses to overwrite an existing file. The host then upgrades each claim to "verified"
                      (with its VP reference) or "removed", or merges claims.
  submit DIR --run NAME --claims D1 D2 D3 D4 D5 --sources S1 S2 S3 S4 S5 --why REASON
                     append the selected exact quotes to a registered VP card;
                     source keys and priority are the host's. Never writes verdicts.
Exit codes: 0 done, 1 refused, 2 usage error.

Usage: hybrid.py scan DIR [--json] | hybrid.py stub DIR | hybrid.py submit DIR [options]
Import: candidates(text), quote_span(draft, quote), input_strings(data), taken_up(cand, draft, strings), MARK, FILES
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ written in the skill directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import guards  # noqa: E402

MARK = 'unverified (memory)'
FILES = ('prior_art.json', 'hypotheses.json', 'tests.json', 'recommendation.json', 'result.json', 'rebound.json',
         'rebound_after.json', 'evidence_table.json', 'material.json', 'moment.json')
NAME = r"[A-Z][^\W\d_]*(?:[-'’][^\W\d_]+)*"
NAMES = r"%s(?:(?:,\s*|\s+and\s+|\s*&\s*)%s)*(?:\s+et al\.?)?" % (NAME, NAME)
REF1 = re.compile(r"(?P<names>%s)\s*\((?P<year>(?:19|20)\d\d)[a-z]?(?=[,;)\s])" % NAMES)
REF2 = re.compile(r"\((?P<names>%s),?\s+(?P<year>(?:19|20)\d\d)[a-z]?\)" % NAMES)
IDENT = re.compile(r"(?i)\b(?:doi:\s*10\.\d{4,9}/[^\s,;)\]]+|arxiv:\s*\d{4}\.\d{4,5}(?:v\d+)?|pmid:\s*\d+)")
NUMBER = re.compile(r"(?<![\w.,])\d+[.,]\d+(?:\s?%)?(?![\w])|(?<![\w.,])\d+\s?%")
THOUSANDS = re.compile(r"^\d{1,3}(?:,\d{3})+$")
STOP = frozenset('''the and for with that this from into are was were has have had not but its their than then when
while also can may will would should which what where about over under between within without each such more most some
any all one two per via use used using only both either other another same these those there here they them very just
like been being does did done about looks quoted'''.split())


def _overlap(a, b):
    return a[0] < b[1] and b[0] < a[1]


WORDNUM = re.compile(
    r"(?i)\b(?:quatre-vingt-dix|quatre-vingts?|soixante-dix|soixante|cinquante|quarante|trente|vingts?|cents?|mille|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand)\b")
WORDVALUE = {'quatre-vingt-dix': 90, 'quatre-vingts': 80, 'quatre-vingt': 80, 'soixante-dix': 70, 'soixante': 60,
             'cinquante': 50, 'quarante': 40, 'trente': 30, 'vingts': 20, 'vingt': 20, 'cents': 100, 'cent': 100, 'mille': 1000,
             'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50, 'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90,
             'hundred': 100, 'thousand': 1000}
INTEGER = re.compile(r"(?<![\w.,/:+-])\d{2,}(?![\w]|[.,]\d)")
STRICT_INTEGER = re.compile(r"(?<![\w.,/:+-])\d+(?![\w]|[.,]\d)")
GROUPED_INTEGER = re.compile(r"(?<![\w.,/:+-])\d{1,3}(?:[ ,\u00a0\u202f]\d{3})+(?![\w]|[.,]\d)")


def candidates(text, strict=False):
    """[{kind, text, start, end, key}] sorted by position: references, identifiers, numbers of a draft text.
    strict: whole numbers (including single-digit label values) and written-out numbers are cues too."""
    out = _candidates(text)
    if strict:
        taken = [(c['start'], c['end']) for c in out]
        for m in GROUPED_INTEGER.finditer(text):
            if any(_overlap((m.start(), m.end()), s) for s in taken):
                continue
            out.append({'kind': 'integer', 'text': m.group(0), 'start': m.start(), 'end': m.end(),
                        'key': {'number': re.sub(r'[ ,\u00a0\u202f]', '', m.group(0))}})
            taken.append((m.start(), m.end()))
        for m in STRICT_INTEGER.finditer(text):
            if any(_overlap((m.start(), m.end()), s) for s in taken):
                continue
            out.append({'kind': 'integer', 'text': m.group(0), 'start': m.start(), 'end': m.end(),
                        'key': {'number': str(int(m.group(0)))}})
        for m in WORDNUM.finditer(text):
            if any(_overlap((m.start(), m.end()), s) for s in taken):
                continue
            v = WORDVALUE[m.group(0).lower()]
            out.append({'kind': 'integer', 'text': m.group(0), 'start': m.start(), 'end': m.end(),
                        'key': {'number': str(v), 'word': m.group(0).lower()}})
        out.sort(key=lambda c: (c['start'], -c['end']))
    return out


def _candidates(text):
    out = []
    for kind, rx in (('reference', REF1), ('reference', REF2)):
        for m in rx.finditer(text):
            first = re.split(r"[-,\s'’]+", m.group('names'))[0]
            span = (m.start(), m.end())
            out.append({'kind': kind, 'text': m.group(0), 'start': span[0], 'end': span[1],
                        'key': {'surname': common.fold(first), 'year': m.group('year')}})
    for m in IDENT.finditer(text):
        raw = m.group(0).rstrip('.')
        out.append({'kind': 'identifier', 'text': raw, 'start': m.start(), 'end': m.start() + len(raw),
                    'key': {'id': re.sub(r'\s+', '', raw.lower())}})
    taken = [(c['start'], c['end']) for c in out]
    for m in NUMBER.finditer(text):
        tok = m.group(0)
        bare = re.sub(r'\s?%$', '', tok)
        if THOUSANDS.match(bare) or any(_overlap((m.start(), m.end()), s) for s in taken):
            continue
        out.append({'kind': 'number', 'text': tok, 'start': m.start(), 'end': m.end(),
                    'key': {'number': bare.replace(',', '.')}})
    # drop a reference found twice (REF1 and REF2 overlap): keep the first of overlapping references
    out.sort(key=lambda c: (c['start'], -c['end']))
    kept = []
    for c in out:
        if c['kind'] == 'reference' and any(k['kind'] == 'reference' and _overlap((c['start'], c['end']), (k['start'], k['end'])) for k in kept):
            continue
        kept.append(c)
    return kept


def quote_span(draft, quote):
    """(start, end) of the quote in the draft (spaces normalised), or None."""
    parts = str(quote or '').split()
    if not parts:
        return None
    m = re.search(r'\s+'.join(re.escape(p) for p in parts), draft)
    return (m.start(), m.end()) if m else None


def sentence_span(draft, start, end):
    left = 0
    for m in re.finditer(r'[.!?]\s|\n', draft[:start]):
        left = m.end()
    m = re.search(r'[.!?](?:\s|$)|\n', draft[end:])
    right = end + m.end() if m else len(draft)
    return left, right


def sentence_around(draft, start, end):
    left, right = sentence_span(draft, start, end)
    return draft[left:right]


def content_words(s):
    return {w for w in common.words(s) if len(w) >= 4 and w not in STOP and not w.isdigit()}


def input_strings(data):
    """[(file, path, string, is_ref_id)] for every string of the files of the card that may take up the draft."""
    out = []

    def walk(x, fname, path, ref_id=False):
        if isinstance(x, str):
            out.append((fname, path, x, ref_id))
        elif isinstance(x, dict):
            # a reference object (VP, or not verified): its "id" is an identifier
            is_ref = isinstance(x.get('id'), str) and re.match(r'(?i)\s*(doi|arxiv|pmid):', x['id']) is not None
            for k, v in x.items():
                walk(v, fname, '%s.%s' % (path, k) if path else k, ref_id=(is_ref and k == 'id'))
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, fname, '%s[%d]' % (path, i))
    for fname in FILES:
        if fname in data:
            walk(data[fname], fname, '')
    return out


def _has_word(folded, word):
    return re.search(r'(?<![a-z0-9])%s(?![a-z0-9])' % re.escape(word), folded) is not None


def _whole_quote_in(quote, text):
    """Normalized whole quote, without matching a prefix of a larger value."""
    quote, text = common.norm_ws(quote), common.norm_ws(text)
    return bool(quote) and re.search(r'(?<!\w)' + re.escape(quote) + r'(?!\w|[.,]\d)', text) is not None


def taken_up(cand, draft, strings):
    """[(file, path, string)] of the strings that take the candidate up (see the module docstring)."""
    out = []
    k = cand['key']
    sent_words = content_words(sentence_around(draft, cand['start'], cand['end'])) if cand['kind'] in ('number', 'integer') else None
    for fname, path, s, is_ref_id in strings:
        folded = common.fold(s)
        if cand['kind'] == 'claim':
            # A partial lexical hit suggests reuse; analyse separates it from
            # an exact whole quote. No percentage of shared words proves meaning.
            words = content_words(cand['text'])
            # Short metric/parameter labels also matter (F1, n). Do not let
            # a minimum word length silently exclude their partial matches.
            labels = {common.fold(w) for w in re.findall(r'(?<!\w)([^\W\d_]\w*)\s*[:=]', cand['text'])}
            labels -= guards.FUNCTION
            values = {c['key']['number'] for c in candidates(s, strict=True)
                      if c['kind'] in ('number', 'integer')}
            hit = (_whole_quote_in(cand['text'], s) or
                   (bool(values & set(k['numbers'])) and
                    bool((words & content_words(s)) or (labels & set(common.words(s))))))
        elif cand['kind'] == 'reference':
            hit = _has_word(folded, k['surname']) and re.search(r'(?<!\d)%s(?!\d)' % k['year'], folded) is not None
        elif cand['kind'] == 'identifier':
            hit = (not is_ref_id) and k['id'] in re.sub(r'\s+', '', folded)
        else:
            n = re.escape(k['number']).replace(r'\.', '[.,]')
            digits = re.search(r'(?<![\d.,])%s(?!\d)' % n, folded) is not None
            word = k.get('word') and _has_word(folded, common.fold(k['word']))
            hit = (digits or bool(word)) and len(content_words(s) & sent_words) >= 2
        if hit:
            out.append((fname, path, s))
    return out


def analyse(draft, claims, data, strict=False):
    """Per candidate: covered_by (claim ids whose quote overlaps it) and taken_up_in (where, marked or not).
    strict (round 3, Terra's blocker on this function): a claim covers an item only when its quote holds the WHOLE sentence of
    the item, so that a pertinent-looking citation cannot cover a wider conclusion. Numeric cues (including written-out
    numbers) become whole prose items; low-level lexical candidates retain their compatibility API.
    Strict rows separate exact taken_up_in from possible_reuse_in. Coverage of
    the source quote does not resolve the meaning of a partial downstream match."""
    spans = []
    for c in claims or []:
        if isinstance(c, dict):
            sp = quote_span(draft, c.get('quote'))
            if sp:
                spans.append((c.get('id'), sp))
    strings = input_strings(data)
    rows = []
    detected = candidates(draft, strict=strict)
    if strict:
        # Lexical tokens are cues for the prose item, not items themselves.
        # Share segmentation with the inventory, including Markdown trimming.
        prose = prose_spans(draft)
        cues = detected
        detected, numeric = [], {}
        for cand in cues:
            span = next(((left, right) for left, right in prose
                         if left <= cand['start'] and cand['end'] <= right), None)
            if span is None:
                continue
            if cand['kind'] in ('number', 'integer'):
                numeric.setdefault(span, set()).add(cand['key']['number'])
            else:
                detected.append(cand)
        for (left, right), numbers in numeric.items():
            detected.append({'kind': 'claim', 'text': draft[left:right], 'start': left, 'end': right,
                             'key': {'numbers': sorted(numbers)}})
        detected.sort(key=lambda c: (c['start'], -c['end']))
    for cand in detected:
        row = dict(cand)
        if strict:
            left, right = next((span for span in prose
                                if span[0] <= cand['start'] and cand['end'] <= span[1]))
            row['covered_by'] = [cid for cid, sp in spans if sp[0] <= left and sp[1] >= right]
        else:
            row['covered_by'] = [cid for cid, sp in spans if _overlap(sp, (cand['start'], cand['end']))]
        matches = taken_up(cand, draft, strings)
        row['taken_up_in'] = []
        if strict:
            row['possible_reuse_in'] = []
        for f, p, s in matches:
            match = {'file': f, 'path': p, 'marked': MARK in s.lower()}
            # Use the full prose span even for identifier/reference cues.
            exact = not strict or _whole_quote_in(draft[left:right], s)
            row['taken_up_in' if exact else 'possible_reuse_in'].append(match)
        rows.append(row)
    return rows


LEAD_WORDS = re.compile(r'(?i)\b(idea|approach|alternative|variant|piste|id[' + chr(0xe9) + r'e]e|approche|neighbour\w*|voisin\w*)\b')


def _claims(work):
    try:
        cj = common.read_json(Path(work) / 'draft_claims.json')
    except (OSError, ValueError):
        return []
    return [c for c in cj.get('claims') or [] if isinstance(c, dict)] if isinstance(cj, dict) else []


def _kind(c):
    k = c.get('kind')
    if k in ('lead', 'magnitude', 'reference'):
        return k
    q = str(c.get('quote') or '')
    if NUMBER.search(q) or INTEGER.search(q) or WORDNUM.search(q):
        return 'magnitude'
    return 'lead' if LEAD_WORDS.search(q) else 'other'


def richness(work):
    """Observable richness of the free phase (adjustment A7): distinct leads and quantified orders of magnitude taken from
    the free draft, and the share of the claims explicitly verified by the host.
    v2 deduplicates normalized quotes only; older formats keep their 60% word-overlap rule."""
    v2 = guards.is_v2(work)
    claims = [c for c in _claims(work) if v2 or c.get('status') != 'removed']
    seen, leads = [], 0
    for c in claims:
        if not v2 and _kind(c) != 'lead':
            continue
        if v2:
            # A number or citation inside an idea does not make the idea disappear.
            if c.get('kind') in ('magnitude', 'reference'):
                continue
            key = common.norm_ws(c.get('quote'))
            if key not in seen:
                leads += 1
                seen.append(key)
            continue
        w = content_words(str(c.get('quote') or ''))
        if not any(w and s and len(w & s) / float(len(w | s)) >= 0.6 for s in seen):
            leads += 1
        seen.append(w)
    magnitudes = sum(1 for c in claims if _kind(c) == 'magnitude' or
                     (v2 and (NUMBER.search(c.get('quote', '')) or INTEGER.search(c.get('quote', '')))))
    verified = sum(1 for c in claims if c.get('status') == 'verified')
    return {'v2': v2, 'claims': len(claims), 'leads': leads, 'magnitudes': magnitudes, 'verified': verified,
            'verified_share': round(verified / float(len(claims)), 3) if claims else 0.0}


def richness_line(r):
    rest = ('other leads remain marked "unverified (memory)"' if r.get('v2')
            else 'the rest is marked "unverified (memory)" or removed')     # historical wording outside v2
    return ('Free phase: %d distinct leads and %d quantified orders of magnitude kept from %d claims; %d%% of the claims '
            'verified (%s).' % (r['leads'], r['magnitudes'], r['claims'], round(100 * r['verified_share']), rest))


# Unit words without a label are fragments, not claims. Keep unknown words:
# this exclusion list must not impose a minimum prose length on v2 inventories.
UNITS = frozenset('''percent percentage pct pourcent pourcentage
ms s sec secs second seconds seconde secondes min mins minute minutes
h hr hrs hour hours heure heures day days jour jours week weeks semaine semaines
month months mois year years an ans annum
mm cm m km mg g kg ml l hz khz mhz ghz kb mb gb tb byte bytes bit bits
usd eur dollar dollars euro euros'''.split())


LABELLED = re.compile(r'^\s*[^\W\d_][\w.-]*\s*(?:=|:|<=|>=|<|>|\u2264|\u2265)\s*\S', re.UNICODE)


def prose_spans(draft):
    """Offsets of prose items, excluding headings, list markers and numeric fragments.

    This is a mechanical inventory, not a semantic claim detector. Keep numeric
    values and author abbreviations whole. A single label or textual lead is
    enough; only bare values, unit-only fragments and headings are excluded.
    """
    spans, offset = [], 0
    for raw in draft.splitlines(keepends=True):
        line = raw.rstrip('\r\n')
        start = re.match(r'^\s*(?:(?:[-*+]|\d+[.)])\s+)?', line).end()
        if line[start:].startswith('#'):
            offset += len(raw)
            continue
        bounds = [start] + [m.end() for m in re.finditer(r'(?<=[.!?])\s+(?=[A-Z])', line)] + [len(line)]
        for left, right in zip(bounds, bounds[1:]):
            while right > left and line[right - 1].isspace():
                right -= 1
            part = line[left:right]
            prose = WORDNUM.sub('', IDENT.sub('', part))
            prose = re.sub(r'(?<!\w)\d+(?:[.,]\d+)?[eE][+-]?\d+(?!\w)', '', prose)
            words = re.findall(r'[^\W_]+', prose, re.UNICODE)
            # A named parameter with a value ("m = 5", "s: 3", "k <= 50") is a claim even when the name is a unit word.
            if IDENT.search(part) or LABELLED.match(part) or any(any(c.isalpha() for c in w) and
                                         re.sub(r'^\d+', '', common.fold(w)) not in UNITS for w in words):
                spans.append((offset + left, offset + right))
        offset += len(raw)
    return spans


def draft_quotes(draft):
    """Starting prose inventory, with only normalized duplicates merged."""
    quotes = []
    for left, right in prose_spans(draft):
        part = draft[left:right]
        if common.norm_ws(part) not in {common.norm_ws(q) for q in quotes}:
            quotes.append(part)
    return quotes


def submissions(work):
    """Resolve draft submissions against exact VP card AND verdict text, offline.

    A submission records an attempt, not factual support. ABSENT and INVALID are
    kept as verdicts; they cannot upgrade an unverified lead into verified evidence.
    """
    work = Path(work)
    try:
        runs = common.read_json(work / 'intake.json').get('vp', {}).get('runs', {})
    except (OSError, ValueError, AttributeError):
        runs = {}
    cache, out, used = {}, [], set()
    for c in _claims(work):
        link = c.get('verification')
        row = {'id': c.get('id'), 'submitted': False, 'verdict': None, 'error': None, 'where': None}
        out.append(row)
        if not isinstance(link, dict):
            continue
        run, cid = link.get('run'), link.get('claim')
        path = runs.get(run) if isinstance(runs, dict) else None
        if not isinstance(path, str) or not cid or not str(link.get('why') or '').strip():
            row['error'] = 'submission needs a registered VP run, claim and decision-priority reason'
            continue
        if (run, cid) in used:
            row['error'] = 'two draft claims cannot count the same VP submission twice'
            continue
        used.add((run, cid))
        row['where'] = '%s/verdicts.json claim %s' % (path.rstrip('/'), cid)
        if run not in cache:
            folder = Path(path) if Path(path).is_absolute() else work / path
            docs = []
            for name in ('card.json', 'verdicts.json'):
                try:
                    docs.append(common.read_json(folder / name))
                except (OSError, ValueError):
                    docs.append({})
            cache[run] = docs
        card, verdicts = cache[run]
        card_rows = [x for x in card.get('claims', []) if isinstance(x, dict) and x.get('id') == cid]
        if len(card_rows) != 1 or ' '.join(str(card_rows[0].get('text') or '').split()) != ' '.join(str(c.get('quote') or '').split()):
            row['error'] = 'submitted quote is not the exact claim in the VP card'
            continue
        source = (card_rows[0].get('source') or {}).get('key')
        if source not in (card.get('sources') or {}):
            row['error'] = 'submitted VP card claim has no declared source'
            continue
        row['submitted'] = True
        vs = [x for x in verdicts.get('claims', []) if isinstance(x, dict) and x.get('id') == cid]
        if not vs:
            continue
        if len(vs) != 1 or ' '.join(str(vs[0].get('text') or '').split()) != ' '.join(str(c.get('quote') or '').split()):
            row['error'] = 'VP verdict belongs to a different claim text'
            continue
        if vs[0].get('status') not in ('FOUND', 'DISTORTED', 'ABSENT', 'INVALID', 'UNVERIFIED', 'SOURCE-UNAVAILABLE'):
            row['error'] = 'unknown VP verdict status'
            continue
        row['verdict'] = vs[0]['status']
    return out


def cmd_submit(a):
    """Put the host's five decision priorities into an existing registered VP card.

    The host supplies source keys after reading the sources; this command never
    guesses a source, runs VP, writes verdicts or upgrades a claim's status.
    """
    work = Path(a.dir)
    try:
        cj = common.read_json(work / 'draft_claims.json')
        claims = cj['claims']
        draft = (work / 'free_draft.md').read_text(encoding='utf-8')
        if cj['draft_sha256'] != common.sha256_file(work / 'free_draft.md'):
            raise ValueError('draft inventory is stale')
        ids = a.claims
        need = min(5, max(len(claims), len(draft_quotes(draft))))
        if len(claims) < need:
            raise ValueError('draft inventory incomplete: %d claims in draft_claims.json for %d sentences in free_draft.md; '
                             'complete the inventory before submitting' % (len(claims), len(draft_quotes(draft))))
        if len(ids) != need or len(set(ids)) != len(ids):
            raise ValueError('select the five most important distinct claims (all if fewer than five)')
        if len(a.sources) != len(ids) or not a.why.strip():
            raise ValueError('one source key per selected claim and a decision-priority reason are required')
        intake = common.read_json(work / 'intake.json')
        path = intake.get('vp', {}).get('runs', {}).get(a.run)
        if not isinstance(path, str):
            raise ValueError('VP run is not registered in intake.json')
        folder = Path(path) if Path(path).is_absolute() else work / path
        cp = folder / 'card.json'
        card = common.read_json(cp)
        for cid, src in zip(ids, a.sources):
            matches = [c for c in claims if c['id'] == cid]
            if len(matches) != 1 or src not in card.get('sources', {}):
                raise ValueError('unknown or duplicate draft claim, or unknown VP source key')
            c = matches[0]
            if quote_span(draft, c.get('quote')) is None:
                raise ValueError('selected quote is not in free_draft.md')
            vid = 'FD_' + cid
            entry = {'id': vid, 'text': c['quote'], 'source': {'key': src}, 'location': 'host-selected claim'}
            existing = [v for v in card['claims'] if v.get('id') == vid]
            if existing and existing != [entry]:
                raise ValueError('VP claim ID collision; existing claims are never overwritten')
            if not existing:
                card['claims'].append(entry)
            c['verification'] = {'run': a.run, 'claim': vid, 'why': a.why}
        # All validation happens before either file changes. Repeating a submission is idempotent.
        common.write_json(cp, card)
        common.write_json(work / 'draft_claims.json', cj)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        print('hybrid.py: refused: %s' % e, file=sys.stderr)
        return 1
    print('%d claims submitted to VP card %s; run VP verification, then inspect every verdict. '
          'Other leads stay unverified (memory).' % (len(ids), cp))
    return 0


IMPACT = {'recommendation.json': 3, 'tests.json': 2, 'result.json': 2}


def priority(work):
    """The claims of the free draft ordered by what they change in the decision (round 3, 6.1): first those taken up in the
    recommendation, the decision rules and the predictions, then the others; verify in this order."""
    work = Path(work)
    draft = (work / 'free_draft.md').read_text(encoding='utf-8') if (work / 'free_draft.md').is_file() else ''
    data = _load(work)
    claims = _claims(work)
    rows = analyse(draft, claims, data, strict=guards.is_r3(work)) if draft else []
    out = []
    for c in claims:
        sp = quote_span(draft, c.get('quote'))
        where, possible, impact = set(), set(), 0
        for r in rows:
            if sp and _overlap(sp, (r['start'], r['end'])):
                for key, target in (('taken_up_in', where), ('possible_reuse_in', possible)):
                    for t in r.get(key, []):
                        target.add(t['file'])
                        impact = max(impact, IMPACT.get(t['file'], 1))
        out.append({'id': c.get('id'), 'status': c.get('status'), 'impact': impact,
                    'taken_up_in': sorted(where), 'possible_reuse_in': sorted(possible)})
    return sorted(out, key=lambda x: (-x['impact'], str(x['id'])))


def _load(work):
    data = {}
    for fname in FILES + ('draft_claims.json',):
        p = Path(work) / fname
        if p.exists():
            try:
                data[fname] = common.read_json(p)
            except ValueError:
                pass
    return data


def cmd_scan(a):
    work = Path(a.dir)
    fp = work / 'free_draft.md'
    if not fp.is_file():
        print('hybrid.py: no free_draft.md in %s' % work, file=sys.stderr)
        return 2
    draft = fp.read_text(encoding='utf-8')
    data = _load(work)
    claims = (data.get('draft_claims.json') or {}).get('claims') if isinstance(data.get('draft_claims.json'), dict) else []
    rows = analyse(draft, claims, data, strict=guards.is_r3(work))
    if a.json:
        print(json.dumps({'draft_sha256': common.sha256_file(fp), 'candidates': rows}, indent=2, ensure_ascii=False))
    else:
        for r in rows:
            where = ', '.join('%s%s' % (t['file'], '' if t['marked'] else ' (not marked)') for t in r['taken_up_in']) or 'not taken up'
            possible = r.get('possible_reuse_in', [])
            if possible:
                where += '; possible reuse to verify [DRAFT-REUSE?]: ' + ', '.join(
                    '%s %s' % (t['file'], t['path']) for t in possible)
            print('%-10s %-40s covered by: %-12s %s' % (r['kind'], r['text'][:40], ','.join(r['covered_by']) or 'no claim', where))
        print('%d item(s) found. A net, not a proof: read the draft yourself.' % len(rows))
    return 0


def cmd_stub(a):
    work = Path(a.dir)
    fp = work / 'free_draft.md'
    if not fp.is_file():
        print('hybrid.py: no free_draft.md in %s' % work, file=sys.stderr)
        return 2
    target = work / 'draft_claims.json'
    if target.exists():
        print('hybrid.py: draft_claims.json already exists; it is not overwritten', file=sys.stderr)
        return 1
    draft = fp.read_text(encoding='utf-8')
    # v2 inventories prose claims, not just numbers and citations; older formats stay unchanged.
    quotes = draft_quotes(draft) if guards.is_v2(work) else [c['text'] for c in candidates(draft)]
    uniq = [{'id': 'D%d' % i, 'quote': q, 'status': 'unverified_memory'} for i, q in enumerate(quotes, 1)]
    if not uniq and guards.is_v2(work):
        print('hybrid.py: no prose claims found; draft_claims.json was not written', file=sys.stderr)
        return 1
    if not uniq:
        uniq = [{'id': 'D1', 'quote': ' '.join(draft.split())[:200], 'status': 'unverified_memory'}]
    common.write_json(target, {'draft_sha256': common.sha256_file(fp), 'claims': uniq})
    print('%s: %d claim(s), all "unverified_memory": verify decision priorities; keep other claims as marked leads'
          % (target, len(uniq)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('scan')
    s.add_argument('dir')
    s.add_argument('--json', action='store_true')
    t = sub.add_parser('stub')
    t.add_argument('dir')
    s = sub.add_parser('submit', help='submit the host-selected five decision priorities to a registered VP card')
    s.add_argument('dir')
    s.add_argument('--run', required=True)
    s.add_argument('--claims', nargs='+', required=True)
    s.add_argument('--sources', nargs='+', required=True)
    s.add_argument('--why', required=True)
    sub.add_parser('priority', help='claims of the free draft ordered by what they change in the decision').add_argument('dir')
    sub.add_parser('richness', help='distinct leads, quantified orders of magnitude and verified share of the free phase').add_argument('dir')
    a = ap.parse_args(argv)
    if a.cmd == 'submit':
        return cmd_submit(a)
    if a.cmd == 'priority':
        print(json.dumps(priority(a.dir), indent=2))
        return 0
    if a.cmd == 'richness':
        r = richness(a.dir)
        print(json.dumps(r))
        print(richness_line(r))
        return 0
    return cmd_scan(a) if a.cmd == 'scan' else cmd_stub(a)


if __name__ == '__main__':
    sys.exit(main())
