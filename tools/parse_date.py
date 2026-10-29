#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Date T from natural language (SKILL.md section 0 "Date T"). Standard library, no network, no model.
T is an exclusive barrier: the gateway serves only documents dated strictly before T. A period named by the user is therefore turned into
the first day AFTER it when the user means "as known at that time" (the period included), and into its first day when the user says
"before" (the period excluded). Rules, in this order of precedence:
  before / avant / antes de / vor <period>       T = first day of the period            "avant mars 2024" -> 2024-03-01 (March excluded)
  until / jusqu'en / hasta / bis <period>        T = first day after the period         "jusqu'au 31 décembre 2019" -> 2020-01-01
  in / en / as of / au / à / im <year|month|quarter|half>
                                                 T = first day after the period         "en 2020" -> 2021-01-01 (documents of 2020 INCLUDED)
                                                                                         "as of 2019" -> 2020-01-01; "en mars 2024" -> 2024-04-01
  as of / au / on / T = <day>                    T = that day (state of knowledge at the start of the day: documents of that day excluded,
                                                 as for the default T = today)           "au 1er janvier 2015" -> 2015-01-01
  start / early / début / Anfang <year>          T = 1 January of the year               "début 2020" -> 2020-01-01
  mid / mi- / Mitte <year>                       T = 1 July of the year                  "mid-2020" -> 2020-07-01
  end / late / fin / Ende <year>                 T = 1 January of the next year          "fin 2020" -> 2021-01-01
  after / since / depuis / between X and Y       a lower bound is not a T (ignored); "between 2015 and 2020" -> the upper bound, included
Inside a longer question only a date with one of these words counts (a bare year is a topic, "the 2008 crisis", never a T); a text that is
only a date ("2020", "March 2024", "2015-01-01") is read with the "in / as of" rule. No date: T = today. A T after today becomes today.
Languages: English, French, Spanish, German month names and words (accents optional). Numeric dates: YYYY-MM-DD, YYYY-MM, and
DD/MM/YYYY or DD.MM.YYYY (MM/DD/YYYY when the text is English).
Usage: parse_date.py "<phrase or question>" [--today YYYY-MM-DD] [--json]
Prints `T = YYYY-MM-DD` and the rule applied, to copy into scope.md (`T = <date> (from "<words>": <rule>)`). Exit 0; 2 on a bad --today.
Import: parse(text, today=None) -> dict(T, rule, matched, kind, others, note)."""
import argparse, datetime as dt, json, pathlib, re, sys, unicodedata
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import report_lang as RL   # noqa: E402  (language of the text, for the numeric day/month order)

MONTHS = {
    1: ['january', 'jan', 'janvier', 'janv', 'enero', 'januar', 'jaenner', 'janner'],
    2: ['february', 'feb', 'fevrier', 'fevr', 'fev', 'febrero', 'februar'],
    3: ['march', 'mar', 'mars', 'marzo', 'marz', 'maerz'],
    4: ['april', 'apr', 'avril', 'avr', 'abril'],
    5: ['may', 'mai', 'mayo'],
    6: ['june', 'jun', 'juin', 'junio', 'juni'],
    7: ['july', 'jul', 'juillet', 'juil', 'julio', 'juli'],
    8: ['august', 'aug', 'aout', 'agosto'],
    9: ['september', 'sept', 'sep', 'septembre', 'septiembre', 'setiembre'],
    10: ['october', 'oct', 'octobre', 'octubre', 'oktober', 'okt'],
    11: ['november', 'nov', 'novembre', 'noviembre'],
    12: ['december', 'dec', 'decembre', 'diciembre', 'dezember', 'dez'],
}
MONTH_OF = {w: m for m, ws in MONTHS.items() for w in ws}
MW = '|'.join(sorted(MONTH_OF, key=len, reverse=True))
Y = r'(?:1[89]|20)\d\d'
EDGE_START = r'debut|early|beginning of|start of|the start of|principios de|comienzos de|inicios de|anfang|fruhjahr'
EDGE_MID = r'mi|mid|middle of|the middle of|mitte|mediados de'
EDGE_END = r'fin|end of|the end of|late|finales de|fines de|ende'
DATE = re.compile(
    rf'(?P<iso>(?P<iy>{Y})-(?P<im>\d\d)(?:-(?P<id>\d\d))?)(?![\d-])'
    rf'|(?P<dmy>\b(?P<d1>\d{{1,2}})(?:er|st|nd|rd|th|\.)?\s+(?:de\s+)?(?P<m1>{MW})\.?,?\s+(?:de\s+|del\s+)?(?P<y1>{Y})\b)'
    rf'|(?P<mdy>\b(?P<m2>{MW})\.?\s+(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y2>{Y})\b)'
    rf'|(?P<num>\b(?P<na>\d{{1,2}})[/.](?P<nb>\d{{1,2}})[/.](?P<ny>{Y})\b)'
    rf'|(?P<my>\b(?P<m3>{MW})\.?,?\s+(?:de\s+|del\s+)?(?P<y3>{Y})\b)'
    rf'|(?P<qtr>\b(?:q|quarter\s+)(?P<q>[1-4])\s+(?P<qy>{Y})\b|\b(?P<qy2>{Y})[\s-]?q(?P<q2>[1-4])\b)'
    rf'|(?P<half>\bh(?P<h>[12])\s+(?P<hy>{Y})\b)'
    rf"|(?P<edge>\b(?P<ew>{EDGE_START}|{EDGE_MID}|{EDGE_END})[\s-]*(?:de\s+|d'|l'annee\s+|the year\s+)?(?P<ey>{Y})\b)"
    rf'|(?P<year>(?<![\d/.-])(?P<y>{Y})(?![\d/-]|\.\d))')
BEFORE = re.compile(r"(?:\b(?:avant|before|prior to|earlier than|antes de|antes del|vor|bevor)(?:\s+(?:le|la|l'|the|el|dem|der|den))?)\s*$")
UNTIL = re.compile(r"(?:\b(?:jusqu'?\s*(?:en|a|au|a la fin de|fin)?|until|till|up to|up until|through|thru|to the end of|hasta(?:\s+(?:el|finales de))?"
                   r"|bis(?:\s+(?:zum|ende|einschliesslich))?|inclusivement|inclus))\s*$")
INAS = re.compile(r"(?:\b(?:en|in|as of|as at|at|on|au|a|le|du|dated|in the year|a la date du|a la date de|a date du|en date du|a fin|al|el|en el|im|am"
                  r"|zum|stand|per|state of|etat au|date)|\bt\s*[:=]|\bdate t\s*[:=]?)\s*$")
AFTER = re.compile(r"(?:\b(?:apres|after|since|depuis|desde|seit|from|de|des|entre|between|zwischen|nach|ab))\s*$")
RANGE_JOIN = re.compile(r"^\s*(?:and|et|y|und|to|a|au|bis|hasta|-|–)\s*$")
TODAY_WORDS = re.compile(r"\b(?:today|now|aujourd'hui|maintenant|hoy|heute|actuellement|currently)\b")
WINDOW = 40   # characters before a date where its qualifier is looked for (a few words)


def norm(text):
    t = unicodedata.normalize('NFKD', str(text or '')).replace('’', "'").replace('ʼ', "'")
    return ''.join(c for c in t if not unicodedata.combining(c)).lower()


def _next_month(y, m): return dt.date(y + (m == 12), m % 12 + 1, 1)


def period(m, lang):
    """(kind, start, end_exclusive) of a date match; None when invalid."""
    g = m.groupdict()
    try:
        if g['iso']:
            y, mo = int(g['iy']), int(g['im'])
            if g['id']: d = dt.date(y, mo, int(g['id'])); return 'day', d, d + dt.timedelta(1)
            return 'month', dt.date(y, mo, 1), _next_month(y, mo)
        if g['dmy']: d = dt.date(int(g['y1']), MONTH_OF[g['m1']], int(g['d1'])); return 'day', d, d + dt.timedelta(1)
        if g['mdy']: d = dt.date(int(g['y2']), MONTH_OF[g['m2']], int(g['d2'])); return 'day', d, d + dt.timedelta(1)
        if g['num']:
            a, b, y = int(g['na']), int(g['nb']), int(g['ny'])
            day, mo = (b, a) if lang == 'en' and a <= 12 else (a, b)
            d = dt.date(y, mo, day); return 'day', d, d + dt.timedelta(1)
        if g['my']: y, mo = int(g['y3']), MONTH_OF[g['m3']]; return 'month', dt.date(y, mo, 1), _next_month(y, mo)
        if g['qtr']:
            q, y = (int(g['q']), int(g['qy'])) if g['q'] else (int(g['q2']), int(g['qy2']))
            s = dt.date(y, 3 * q - 2, 1); return 'quarter', s, _next_month(y, 3 * q)
        if g['half']: h, y = int(g['h']), int(g['hy']); return 'half', dt.date(y, 6 * h - 5, 1), _next_month(y, 6 * h)
        if g['edge']:
            y, w = int(g['ey']), g['ew']
            if re.fullmatch(EDGE_START, w): p = dt.date(y, 1, 1)
            elif re.fullmatch(EDGE_MID, w): p = dt.date(y, 7, 1)
            else: p = dt.date(y + 1, 1, 1)
            return 'point', p, p
        if g['year']: y = int(g['y']); return 'year', dt.date(y, 1, 1), dt.date(y + 1, 1, 1)
    except (ValueError, KeyError):
        return None
    return None


LABEL = {'day': 'that day', 'month': 'that month', 'year': 'that year', 'quarter': 'that quarter', 'half': 'that half-year'}


def _rule(qual, kind, start, end, words):
    if kind == 'point':
        return end, f'"{words}" = a point in the year: T = {end.isoformat()} (the gateway serves documents dated strictly before T)'
    if qual == 'before':
        return start, f'"{words}" = before {LABEL[kind]}: documents of {LABEL[kind]} are EXCLUDED; T = {start.isoformat()}, its first day'
    if qual == 'until' or kind != 'day':
        return end, (f'"{words}" = the state of knowledge at the end of {LABEL[kind]}: documents dated in {LABEL[kind]} are INCLUDED; '
                     f'T = {end.isoformat()}, the first day after it (the gateway serves documents dated strictly before T)')
    return start, (f'"{words}" = the state of knowledge at the start of that day: documents dated that day are EXCLUDED, as for the default '
                   f'T = today; T = {start.isoformat()}')


def parse(text, today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    text = unicodedata.normalize('NFC', str(text or '')); n = norm(text); lang = RL.detect(text)
    found, prev = [], None
    for m in DATE.finditer(n):
        p = period(m, lang)
        if not p: continue
        before = n[max(0, m.start() - WINDOW):m.start()]
        if prev is not None and prev['qual'] == 'after' and RANGE_JOIN.match(n[prev['end_pos']:m.start()]): qual = 'until'
        elif BEFORE.search(before): qual = 'before'
        elif UNTIL.search(before): qual = 'until'
        elif AFTER.search(before): qual = 'after'
        elif INAS.search(before): qual = 'in'
        else: qual = None
        if p[0] == 'point' and qual is None: qual = 'in'           # "fin 2020", "mid-2020" are dates of knowledge by themselves
        cur = {'qual': qual, 'kind': p[0], 'start': p[1], 'end': p[2], 'words': text_slice(text, n, m), 'end_pos': m.end()}
        found.append(cur); prev = cur
    usable = [f for f in found if f['qual'] in ('before', 'until', 'in')]
    if not usable:
        only = [f for f in found if f['qual'] is None]
        if len(only) == 1 and not re.sub(r'[\W_]+', '', n.replace(norm(only[0]['words']), '', 1)):   # the text is only a date
            only[0]['qual'] = 'in'; usable = only
    note = ''
    if not usable:
        ignored = [f['words'] for f in found]
        rule = ('no date of knowledge in the text: T = today' + (f' (ignored: {", ".join(ignored)}: a year without "in", "before", "as of"... '
                'is a topic, not a T; a lower bound "after/since" is not a T)' if ignored else '')
                + ('' if not TODAY_WORDS.search(n) else '; "today" read as today'))
        return {'T': today.isoformat(), 'rule': rule, 'matched': None, 'kind': None, 'others': [], 'note': '', 'language': lang}
    f = usable[0]
    T, rule = _rule(f['qual'], f['kind'], f['start'], f['end'], f['words'])
    others = [x['words'] for x in usable[1:] if _rule(x['qual'], x['kind'], x['start'], x['end'], x['words'])[0] != T]
    if others: note = f'several dates of knowledge in the text; the first one is kept ({f["words"]}); others: {", ".join(others)}'
    if T > today:
        note = (note + '; ' if note else '') + f'T {T.isoformat()} is after today: T = today ({today.isoformat()})'
        T = today
    return {'T': T.isoformat(), 'rule': rule, 'matched': f['words'], 'kind': f['kind'], 'others': others, 'note': note, 'language': lang}


def text_slice(text, n, m):
    """The words of the original text matching m (NFC text: one character per letter, so positions agree with the normalised text)."""
    s = unicodedata.normalize('NFC', str(text or ''))
    return s[m.start():m.end()] if len(norm(s)) == len(n) else n[m.start():m.end()]


def main(argv=None):
    ap = argparse.ArgumentParser(description='Date T from natural language (exclusive barrier: documents dated strictly before T).')
    ap.add_argument('text', nargs='+'); ap.add_argument('--today'); ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    today = None
    if a.today:
        try: today = dt.date.fromisoformat(a.today)
        except ValueError: print(f'parse_date.py: --today expects YYYY-MM-DD: {a.today!r}', file=sys.stderr); return 2
    r = parse(' '.join(a.text), today)
    if a.json: print(json.dumps(r, ensure_ascii=False, indent=1)); return 0
    print(f"T = {r['T']}")
    print(f"rule: {r['rule']}")
    if r['note']: print(f"note: {r['note']}")
    print(f"scope.md: T = {r['T']} (" + (f'from "{r["matched"]}": ' if r['matched'] else '') + f"{r['rule']})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
