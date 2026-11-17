#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Named datasets, models, metrics, benchmarks and libraries of Frontier v2 (SKILL.md "Frontier v2: the path", stage 3).
Offline, standard library. A hypothesis or a test that names an element must say whether that element exists: ideas written
by a model have been shown to name datasets that do not exist. named_elements.json keeps one record per element:

  existence   verified       evidence {"kind": "material", "item": <name of an item of material.json found through VP's gateway>}
                             or {"kind": "reference", "ref": {id, run, claim}, "fragment": <a fragment VP verified for that
                             claim, FOUND, that holds the name>}
              host_checked   evidence {"how": <what the host looked at>}: shown as checked by the host, not by VP
              unverified     evidence {"why": <...>}: shown as "unverified (memory)"
              not_found      evidence {"queries": [...]}: searched, nothing found; shown "NOT FOUND ... do not rely on it"
Nothing is deleted: a not-found or unverified element stays on the card, marked. Only a "verified" that does not resolve is an
error ([NAMED-VERIFY] in tools/check.py).

Subcommands:
  add DIR --name N --kind dataset|model|metric|benchmark|library --used-in T1 [--used-in T2 ...]
      exactly one of: --material ITEM | --ref-id ID --run RUN --claim A1 --fragment TEXT | --host HOW | --unverified WHY |
      --not-found --query Q [--query Q ...]
      Records (or updates) the element; refuses a "verified" whose evidence does not resolve.
  list DIR     Prints named_elements.json.
Usage: named.py add|list DIR ...
Exit codes: 0 done, 1 refused, 2 usage error.
Import: element_problem(work, intake, material, el)
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ written in the skill directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

KINDS = ('dataset', 'model', 'metric', 'benchmark', 'library')
EXISTENCE = ('verified', 'host_checked', 'unverified', 'not_found')


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def norm(s):
    return re.sub(r'\s+', ' ', str(s or '').strip().lower())


def element_problem(work, intake, material, el, ck=None):
    """Why the evidence of an element does not resolve (a message), or None. `material` is material.json (or None); `ck` is
    the tools/check.py module when the caller is the check itself (so that it is not imported a second time)."""
    ex, ev = el.get('existence'), el.get('evidence')
    if ex not in EXISTENCE:
        return 'existence must be one of %s' % ', '.join(EXISTENCE)
    if not isinstance(ev, dict):
        return 'evidence is required'
    if ex == 'host_checked':
        return None if len(str(ev.get('how', '')).strip()) >= 20 else 'host_checked needs evidence.how: what the host looked at (20 characters or more)'
    if ex == 'unverified':
        return None if len(str(ev.get('why', '')).strip()) >= 10 else 'unverified needs evidence.why (10 characters or more)'
    if ex == 'not_found':
        qs = [q for q in ev.get('queries') or [] if isinstance(q, str) and q.strip()]
        return None if qs else 'not_found needs the queries that were searched'
    if ev.get('kind') == 'material':
        items = [i for i in (material.get('items') if isinstance(material, dict) else None) or [] if isinstance(i, dict)]
        hit = [i for i in items if i.get('via') == 'gateway' and norm(i.get('name')) and norm(i.get('name')) == norm(ev.get('item'))]
        if not hit:
            return 'no item named %r found through the gateway in material.json' % ev.get('item')
        n, it = norm(el.get('name')), norm(ev.get('item'))
        return None if n and (n in it or it in n) else 'the element %r is not the item %r' % (el.get('name'), ev.get('item'))
    if ev.get('kind') == 'reference':
        import r3check  # noqa: E402
        if ck is None:
            import check as ck  # noqa: E402 (lazy: check imports this directory's modules)
        check = ck
        ref = ev.get('ref')
        if not isinstance(ref, dict):
            return 'evidence.ref = {id, run, claim} is required'
        status, code, msg = check.ref_check(check.VPRuns(Path(work), intake), ref)
        if code or status != 'FOUND':
            return 'the reference is %s (%s): only a FOUND claim can verify an element' % (status or 'unreadable', code or msg)
        v = r3check.vp_claim(work, intake, ref.get('run'), ref.get('claim'))
        if v is None or not r3check.fragment_ok(ev.get('fragment'), v['fragments']):
            return 'the fragment is not one that VP verified for claim %s' % ref.get('claim')
        if norm(el.get('name')) not in norm(ev.get('fragment')):
            return 'the verified fragment does not hold the name %r' % el.get('name')
        return None
    return 'a verified element needs evidence.kind "material" or "reference"'


def load(work):
    p = Path(work) / 'named_elements.json'
    return common.read_json(p) if p.is_file() else {'version': 1, 'elements': []}


def cmd_add(a):
    work = Path(a.dir)
    modes = [a.material is not None, a.ref_id is not None, a.host is not None, a.unverified is not None, bool(a.not_found)]
    if sum(modes) != 1:
        print('named.py: give exactly one of --material, --ref-id (with --run --claim --fragment), --host, --unverified, --not-found', file=sys.stderr)
        return 2
    if not a.used_in:
        print('named.py: --used-in is required (a test or hypothesis id)', file=sys.stderr)
        return 2
    el = {'name': a.name.strip(), 'kind': a.kind, 'used_in': list(a.used_in), 'checked_utc': utc_now()}
    if a.material is not None:
        el.update(existence='verified', evidence={'kind': 'material', 'item': a.material})
    elif a.ref_id is not None:
        if not (a.run and a.claim and a.fragment):
            print('named.py: --ref-id needs --run, --claim and --fragment', file=sys.stderr)
            return 2
        el.update(existence='verified', evidence={'kind': 'reference', 'ref': {'id': a.ref_id, 'run': a.run, 'claim': a.claim},
                                                   'fragment': a.fragment})
    elif a.host is not None:
        el.update(existence='host_checked', evidence={'how': a.host})
    elif a.unverified is not None:
        el.update(existence='unverified', evidence={'why': a.unverified})
    else:
        el.update(existence='not_found', evidence={'queries': list(a.query or [])})
    try:
        intake = common.read_json(work / 'intake.json')
        material = common.read_json(work / 'material.json') if (work / 'material.json').is_file() else None
    except (OSError, ValueError) as e:
        print('named.py: %s' % e, file=sys.stderr)
        return 2
    why = element_problem(work, intake, material, el)
    if why:
        print('named.py: refused: %s' % why, file=sys.stderr)
        return 1
    data = load(work)
    old = next((e for e in data['elements'] if norm(e.get('name')) == norm(el['name']) and e.get('kind') == el['kind']), None)
    if old is not None:
        el['id'] = old['id']
        el['used_in'] = sorted(set(old.get('used_in') or []) | set(el['used_in']))
        data['elements'][data['elements'].index(old)] = el
    else:
        el['id'] = 'N%d' % (1 + max([int(e['id'][1:]) for e in data['elements'] if re.fullmatch(r'N\d+', str(e.get('id')))] or [0]))
        data['elements'].append(el)
    common.write_json(work / 'named_elements.json', data)
    print(json.dumps(el, ensure_ascii=False))
    return 0


def cmd_list(a):
    print(json.dumps(load(a.dir), ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog='Usage: named.py add|list DIR ...')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('add')
    s.add_argument('dir')
    s.add_argument('--name', required=True)
    s.add_argument('--kind', required=True, choices=KINDS)
    s.add_argument('--used-in', dest='used_in', action='append')
    s.add_argument('--material')
    s.add_argument('--ref-id', dest='ref_id')
    s.add_argument('--run')
    s.add_argument('--claim')
    s.add_argument('--fragment')
    s.add_argument('--host')
    s.add_argument('--unverified')
    s.add_argument('--not-found', dest='not_found', action='store_true')
    s.add_argument('--query', action='append')
    sub.add_parser('list').add_argument('dir')
    a = ap.parse_args(argv)
    return {'add': cmd_add, 'list': cmd_list}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
