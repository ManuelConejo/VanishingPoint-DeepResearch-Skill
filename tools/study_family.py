#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Study families: the sources of one run that are one study under several forms (preprint and published article, versions, trial
registry record and its report, full report and journal article). SKILL.md section 0 "Identity of sources" (one study under several
identifiers = one entry) and section 4 "Triangulate" (count clusters, not documents) say what to do; this tool finds, mechanically, the
pairs the writer left as separate bibliography entries, so that the tools that count sources count studies:
  check 14 of validate_card.py (tools/cross_source.py): a cross-source statement citing two versions of one study cites one study;
                a "three trials [1][2][3]" whose numbers hold fewer studies than the count says is flagged too;
  tools/summary.py: the number of distinct studies that carry the report (lowered-coverage notice under `summary.min_sources`).
Standard library, no network, no model. Signals (config.json `study_family`, every threshold named there):
  identifier   the same normalised identifier on two entries (card fields, identifiers written in the bibliography line; a DataCite
               arXiv DOI 10.48550/arXiv.<id> = arxiv:<id>; arXiv version suffix dropped);
  relation     a Crossref-style relation recorded in card.json (`relation`: {"is-preprint-of": [{"id": ..., "id-type": "doi"}], ...},
               or `related`: ["doi:...", ...]) whose type is in `relation_types` and whose target is another entry's identifier;
  registry     the same trial or review registration number (`registry_patterns`: NCT, ISRCTN, EudraCT, PROSPERO...) in the
               identifiers, the title or the bibliography line of two entries;
  (title links only between two entries that each carry an identifier kind of `title_link_kinds`: scholarly records, not
  court decisions, statutes, data series, code or local documents, whose titles repeat by construction)
  title+author word overlap (Jaccard of the content words of the titles) >= `title_min_similarity`, same first author (bibliography
               line), years at most `year_gap_max` apart when both are known;
  title        overlap >= `title_only_min_similarity` when a first author is missing on one side (years as above).
A family is the transitive closure of these links (union-find). Card key S<n> = bibliography number [n] (SKILL.md section 6).
Usage: study_family.py RUN_DIR [--json]     prints the families of more than one entry (exit 0)
Import: families(card, md) -> dict; of_dir(dir) -> dict; by_number(fam) -> {n: family}; count(fam, numbers) -> int."""
import json, pathlib, re, sys, unicodedata
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P))
import report_lang as RL   # noqa: E402

CFG = json.loads((P / 'config.json').read_text(encoding='utf-8')).get('study_family') or {}
NOT_IDS = {'title', 'note', 'relation', 'related', 'location', 'year', 'authors', 'first_author', 'desc'}
STOP = {w for L in RL.LANGS.values() for w in L['stop']} | set(CFG.get('extra_stopwords') or [])
BIB_ID = re.compile(r'\b([a-z][a-z0-9]{1,15}):(\S+)', re.I)
DOI_URL = re.compile(r'(?:https?://(?:dx\.)?doi\.org/|\bdoi:\s*)(10\.\d{4,9}/\S+)', re.I)
NOT_AUTHORS = {_f for _f in (CFG.get('not_authors') or [])}
DISTINCT = set(CFG.get('distinct_words') or [])
TITLE_KINDS = set(CFG.get('title_link_kinds') or [])
YEAR = re.compile(r'(?<!\d)(19\d\d|20\d\d)(?!\d)')


def _fold(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(s or '')) if not unicodedata.combining(c)).casefold()


def norm_id(kind, value):
    """('doi', 'https://doi.org/10.48550/arXiv.2301.00001v2') -> {'doi:10.48550/arxiv.2301.00001v2', 'arxiv:2301.00001'}: lower case,
    trailing punctuation removed, an arXiv id without its version suffix."""
    k = _fold(kind).strip(); v = _fold(value).strip().rstrip('.,;)]>')
    v = re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:)', '', v) if k == 'doi' else re.sub(r'^' + re.escape(k) + r':', '', v)
    if not v: return set()
    if k == 'arxiv': return {'arxiv:' + re.sub(r'v\d+$', '', v)}
    out = {f'{k}:{v}'}
    m = re.fullmatch(r'10\.48550/arxiv\.(.+)', v) if k == 'doi' else None
    if m: out.add('arxiv:' + re.sub(r'v\d+$', '', m.group(1)))
    return out


def registry_ids(text):
    out = set()
    for name, rx in (CFG.get('registry_patterns') or {}).items():
        for m in re.finditer(rx, str(text or ''), re.I):
            out.add('reg:' + re.sub(r'[\s/_-]+', '', m.group(0)).upper())
    return out


def bibliography(md):
    """{n: line} of the bibliography entries of REPORT.md (any language of the table)."""
    out = {}
    for line in RL.section(md or '', 'Bibliography').splitlines():
        m = re.match(r'^\s*\[(\d{1,3})\]\s*(.*)$', line)
        if m: out[int(m.group(1))] = m.group(2).strip()
    return out


def first_author(line):
    """Family name of the first author of a bibliography line ("Martineau et al. Title...", "Martineau AR, Jolliffe DA. ...",
    "A. R. Martineau, ..."): the first word of three letters or more, not all capitals, before the first separator; None when the line
    opens on something else (an identifier, a quoted title)."""
    head = re.split(r',|;|\(|\bet al\b|\band\b|&|(?<=[^\W\d_]{2})\. (?=[A-Z][a-z])|:', line or '', maxsplit=1)[0]
    if BIB_ID.match((line or '').strip()) or len(head.split()) > int(CFG.get('author_words_max', 4)): return None
    for w in re.findall(r'[^\W\d_][^\W\d_\'’-]*', head):
        if len(w) >= 3 and not w.isupper(): return None if _fold(w) in NOT_AUTHORS else _fold(w)
    return None


def words(title):
    """Content words of a title: letters only (numbers, such as a follow-up length or a year, do not count), at least min_token_chars long,
    minus the frequent words of tools/report_lang.py and extra_stopwords."""
    n = int(CFG.get('min_token_chars', 3))
    return {w for w in re.findall(r'[^\W\d_]+', _fold(title)) if len(w) >= n and w not in STOP}


def similarity(a, b):
    """Jaccard of the content words; 0 when either title has fewer than title_min_words of them, or when a word of distinct_words
    (a pilot, a feasibility study: a separate study by design) is in one title only."""
    A, B = words(a), words(b)
    if min(len(A), len(B)) < int(CFG.get('title_min_words', 1)) or (A ^ B) & DISTINCT: return 0.0
    return len(A & B) / len(A | B)


def _num(key):
    m = re.fullmatch(r'S(\d+)', str(key)); return int(m.group(1)) if m else None


def families(card, md=''):
    """{'family': {key: 'F<k>'}, 'groups': [{'family', 'members', 'links': [{'a', 'b', 'signal', 'value'}]}] (groups of 2+ only),
    'entries': number of entries, 'studies': number of families}. Keys = card.json source keys, plus B<n> for a bibliography entry
    with no card key."""
    src = (card or {}).get('sources') if isinstance((card or {}).get('sources'), dict) else {}
    bib = bibliography(md); ent = {}
    for k, s in src.items():
        if isinstance(s, dict): ent[k] = {'desc': s, 'line': bib.get(_num(k), '')}
    for n, line in bib.items():
        if f'S{n}' not in ent: ent[f'B{n}'] = {'desc': {}, 'line': line}
    for k, e in ent.items():
        d, line = e['desc'], e['line']
        ids = set()
        for f, v in d.items():
            if f not in NOT_IDS and isinstance(v, str) and v.strip(): ids |= norm_id(f, v)
        for m in BIB_ID.finditer(line): ids |= norm_id(m.group(1), m.group(2))
        for m in DOI_URL.finditer(line): ids |= norm_id('doi', m.group(1))
        ids = {i for i in ids if not i.startswith(('http:', 'https:'))}
        title = d.get('title') or line
        e.update(ids=ids, kinds={i.split(':', 1)[0] for i in ids}, reg=registry_ids(' '.join([title, line] + [v for f, v in d.items() if isinstance(v, str) and f not in NOT_IDS])),
                 title=title, author=_fold(d.get('first_author')) or first_author(line),
                 year=int(YEAR.search(line).group(1)) if YEAR.search(line) else None, rel=set())
        rel_types = set(CFG.get('relation_types') or [])
        for t, targets in (d.get('relation') or {}).items() if isinstance(d.get('relation'), dict) else ():
            if t in rel_types:
                for x in targets if isinstance(targets, list) else [targets]:
                    if isinstance(x, dict) and x.get('id'): e['rel'] |= norm_id(x.get('id-type') or 'doi', x['id'])
        for x in d.get('related') or [] if isinstance(d.get('related'), list) else []:
            if isinstance(x, str) and ':' in x: e['rel'] |= norm_id(*x.split(':', 1))
    parent = {k: k for k in ent}

    def root(k):
        while parent[k] != k: parent[k] = parent[parent[k]]; k = parent[k]
        return k
    links = []
    keys = sorted(ent, key=lambda k: (k[0] != 'S', int(k[1:]) if k[1:].isdigit() else 0, k))
    tmin, tonly, gap = float(CFG.get('title_min_similarity', 1.1)), float(CFG.get('title_only_min_similarity', 1.1)), CFG.get('year_gap_max')
    for i, a in enumerate(keys if CFG.get('enabled') is not False else []):     # disabled: every entry is its own study
        for b in keys[i + 1:]:
            A, B = ent[a], ent[b]; sig = None
            if A['ids'] & B['ids']: sig = ('identifier', sorted(A['ids'] & B['ids'])[0])
            elif (A['rel'] & B['ids']) or (B['rel'] & A['ids']): sig = ('relation', sorted((A['rel'] & B['ids']) | (B['rel'] & A['ids']))[0])
            elif A['reg'] & B['reg']: sig = ('registry', sorted(A['reg'] & B['reg'])[0])
            elif (A['kinds'] & TITLE_KINDS) and (B['kinds'] & TITLE_KINDS):
                if gap is not None and A['year'] and B['year'] and abs(A['year'] - B['year']) > int(gap): continue
                s = similarity(A['title'], B['title'])
                if A['author'] and B['author']:
                    if A['author'] == B['author'] and s >= tmin: sig = ('title+author', round(s, 2))
                elif s >= tonly: sig = ('title', round(s, 2))
            if sig:
                links.append({'a': a, 'b': b, 'signal': sig[0], 'value': sig[1]})
                ra, rb = root(a), root(b)
                if ra != rb: parent[rb] = ra
    groups = {}
    for k in keys: groups.setdefault(root(k), []).append(k)
    fam, out = {}, []
    for i, (r, members) in enumerate(sorted(groups.items(), key=lambda kv: keys.index(kv[1][0])), 1):
        for k in members: fam[k] = f'F{i}'
        if len(members) > 1: out.append({'family': f'F{i}', 'members': members, 'links': [l for l in links if l['a'] in members]})
    return {'family': fam, 'groups': out, 'entries': len(ent), 'studies': len(groups)}


def of_dir(folder):
    d = pathlib.Path(folder)
    try: card = json.loads((d / 'card.json').read_text(encoding='utf-8'))
    except (OSError, ValueError): card = {}
    try: md = (d / 'REPORT.md').read_text(encoding='utf-8', errors='replace')
    except OSError: md = ''
    return families(card if isinstance(card, dict) else {}, md)


def by_number(fam):
    """{n: family} for the bibliography numbers (S<n> or B<n>), the form tools/cross_source.py reads."""
    out = {}
    for k, f in (fam or {}).get('family', {}).items():
        if k[1:].isdigit(): out[int(k[1:])] = f
    return out


def count(fam_by_n, numbers):
    """Number of distinct studies among the bibliography numbers (a number unknown to the map is its own study)."""
    return len({(fam_by_n or {}).get(n, f'n{n}') for n in numbers})


if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    if not a: print(__doc__); sys.exit(2)
    f = of_dir(a[0])
    if '--json' in sys.argv: print(json.dumps(f, ensure_ascii=False, indent=1)); sys.exit(0)
    print(f"{f['entries']} entries, {f['studies']} distinct studies")
    for g in f['groups']:
        print(f"{g['family']}: {' = '.join(g['members'])} (" + '; '.join(f"{l['a']}-{l['b']} {l['signal']} {l['value']}" for l in g['links']) + ')')
