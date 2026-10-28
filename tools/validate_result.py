#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Shape check of result.json (the machine annex of a run).
Usage: validate_result.py result.json   -> list of problems (empty = OK), exit code 1 if there are any. Offline, no dependency.
Import: problems(dict) -> [str]; CRITERIA list."""
import json, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sources as _reg   # noqa: E402  (source registry: identifier kinds and their forms)

CRITERIA = ['population', 'intervention_exposure', 'comparator', 'results', 'study_design', 'date_language_type']
FORMS = {i['prefix']: i['form'] for i in _reg.IDS if i['form']}   # identifier kinds of the source declarations (tools/sources/; same kinds as validate_card.IDS)
CODE = r'[^\s:@][^\s@]*@[0-9a-f]{7,40}'                                               # code: `<file path>@<SHA>` (SKILL.md section 0, identity of sources)
ID = re.compile(r'^(%s|%s)$' % ('|'.join(f'{k}:(?:{v})' for k, v in FORMS.items()), CODE), re.I)
MAX = 50


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
        if not ID.match(ident): pb.append(f'{p}.id: identifier {"/".join(k + ":" for k in FORMS)} or <path>@<SHA> expected, got {ident!r}')
        if ident.lower() in seen: pb.append(f'{p}.id: duplicate {ident}')
        seen.add(ident.lower())
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
    if conf != sorted(conf, reverse=True): pb.append('studies: confidence not non-increasing')
    return pb


if __name__ == '__main__':
    try: r = json.load(open(sys.argv[1], encoding='utf-8'))
    except Exception as e: print(f'unreadable JSON: {e}'); sys.exit(1)
    p = problems(r)
    print('\n'.join(p) if p else 'OK')
    sys.exit(1 if p else 0)
