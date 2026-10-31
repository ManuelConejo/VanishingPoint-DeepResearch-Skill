#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Shape check of result.json (the machine annex of a run).
Usage: validate_result.py result.json   -> list of problems (empty = OK), exit code 1 if there are any; warnings printed after them
(prefix `warning:`), never blocking. Offline, no dependency.
Code identifiers: `repo:<owner>/<name>/<path>@<40-hex SHA>` (repository named, full SHA) is the complete form; the older `<path>@<SHA>`
(no repository) and any SHA shorter than 40 hex are still accepted, with a warning (code_warnings).
Import: problems(dict) -> [str]; warnings(dict) -> [str]; code_warnings(ident) -> [str]; CRITERIA list."""
import json, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sources as _reg   # noqa: E402  (source registry: identifier kinds and their forms)
from sources._common import arxiv_id   # noqa: E402

CRITERIA = ['population', 'intervention_exposure', 'comparator', 'results', 'study_design', 'date_language_type']
FORMS = {i['prefix']: i['form'] for i in _reg.IDS if i['form']}   # identifier kinds of the source declarations (tools/sources/; same kinds as validate_card.IDS)
CODE = r'(?![a-z][a-z0-9]*:)[^\s:@][^\s@]*@[0-9a-f]{7,40}'                            # code: `<file path>@<SHA>` (SKILL.md section 0, identity of sources); a `<prefix>:` start is an identifier kind, never a path
ID = re.compile(r'^(%s|%s)$' % ('|'.join(f'{k}:(?:{v})' for k, v in FORMS.items()), CODE), re.I)
MAX = 50
SHA = re.compile(r'@([0-9a-f]+)$', re.I)


def code_warnings(ident):
    """Warnings of a code identifier (empty for a non-code one or the complete form repo:<owner>/<name>/<path>@<40-hex SHA>): a SHA shorter
    than 40 hex (ambiguous over time, not readable by the gateway's code-file); `<path>@<SHA>` without a repository (ambiguous with several Y)."""
    s = str(ident or '').strip(); low = s.lower()
    is_code = low.startswith(('repo:', 'local:')) or (re.fullmatch(CODE, s, re.I) is not None and not re.match(r'[a-z][a-z0-9]*:', low))
    if not is_code: return []
    out = []
    m = SHA.search(s)
    if m and len(m.group(1)) < 40: out.append(f'abbreviated SHA ({len(m.group(1))} hex characters, 40 expected): {s}')
    if not low.startswith(('repo:', 'local:')): out.append(f'no repository named (repo:<owner>/<name>/<path>@<40-hex SHA> expected): {s}')
    return out


def warnings(r):
    """Non-blocking deviations of result.json (code identifiers, code_warnings)."""
    st = r.get('studies') if isinstance(r, dict) else None
    return [f'studies[{i}].id: {w}' for i, e in enumerate(st if isinstance(st, list) else []) if isinstance(e, dict) for w in code_warnings(e.get('id'))]


def problems(r, max_studies=MAX):
    pb = []
    if not isinstance(r, dict): return ['root: JSON object expected']
    for k in ('studies', 'saturation', 'calls_used'):
        if k not in r: pb.append(f'missing field: {k}')
    st = r.get('studies')
    if not isinstance(st, list): return pb + ['studies: list expected']
    if len(st) > max_studies: pb.append(f'studies: {len(st)} > {max_studies}')
    if not isinstance(r.get('saturation', ''), str) or not r.get('saturation', '').strip(): pb.append('saturation: non-empty text expected')
    if not isinstance(r.get('calls_used', 0), int): pb.append('calls_used: integer expected')
    v = r.get('verification')
    if v is not None and not (isinstance(v, dict) and isinstance(v.get('entries_removed'), int) and isinstance(v.get('rule'), str)):
        pb.append('verification: {entries_removed: integer, rule: text} expected')
    seen, conf = set(), []
    for i, e in enumerate(st):
        p = f'studies[{i}]'
        if not isinstance(e, dict): pb.append(f'{p}: object expected'); continue
        ident = str(e.get('id', ''))
        if not ID.match(ident): pb.append(f'{p}.id: identifier {"/".join(k + ":" for k in FORMS)} or <path>@<SHA> expected, got {ident!r}')   # repo: is one of FORMS (github-repo)
        key = f'arxiv:{arxiv_id(ident)}' if ident.lower().startswith(('doi:', 'arxiv:')) and arxiv_id(ident) else ident.lower()   # arXiv DOI = arxiv:<id>, version dropped
        if key in seen: pb.append(f'{p}.id: duplicate {ident}')
        seen.add(key)
        if not str(e.get('title', '')).strip(): pb.append(f'{p}.title: empty')
        if not re.match(r'^\d{4}$', str(e.get('year', ''))): pb.append(f'{p}.year: 4-digit year expected')
        c = e.get('confidence')
        if not isinstance(c, (int, float)) or isinstance(c, bool) or not 0 <= c <= 1: pb.append(f'{p}.confidence: number between 0 and 1 expected')
        else: conf.append(c)
        cr = e.get('criteria')
        if not isinstance(cr, dict): pb.append(f'{p}.criteria: object expected')
        else:
            for k in CRITERIA:
                if not isinstance(cr.get(k), str): pb.append(f'{p}.criteria.{k}: text expected')
        if e.get('basis') not in ('abstract', 'title'): pb.append(f'{p}.basis: "abstract" or "title" expected')
        if 'borderline' in e:   # SKILL.md section 4 step 2 / section 6: optional flag of a kept borderline entry
            if not isinstance(e['borderline'], bool): pb.append(f'{p}.borderline: true or false expected')
            elif e['borderline'] and not str(e.get('borderline_reason') or '').strip(): pb.append(f'{p}.borderline_reason: non-empty text expected when borderline is true')
    if conf != sorted(conf, reverse=True): pb.append('studies: confidence not non-increasing')
    return pb


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] in ('-h', '--help'): print(__doc__); sys.exit(0 if sys.argv[1:] in (['-h'], ['--help']) else 2)
    try: r = json.load(open(sys.argv[1], encoding='utf-8'))
    except Exception as e: print(f'unreadable JSON: {e}'); sys.exit(1)
    p = problems(r); w = warnings(r)
    print('\n'.join(p) if p else 'OK')
    if w: print('\n'.join('warning: ' + x for x in w))
    sys.exit(1 if p else 0)
