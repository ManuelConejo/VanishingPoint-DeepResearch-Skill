#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Project context of Frontier (SKILL.md step 0-quater): key numbers of the user's own project. Offline, standard library.

intake.json may hold a "context" block: objective, data available, constraints and KEY NUMBERS (number of periods, number
of units, information coefficient, costs, noise ...). tools/sim.py uses the confirmed ones for the power of a test
(--context), and says so when it cannot. This tool finds CANDIDATES in the user's own files and records the ones the host
confirms. It never invents a number and never reads a folder the user did not name.

Subcommands (DIR = the Frontier working directory):
  extract DIR [--json]
        Reads the README, result and lesson files of the folders named in intake.json project_dirs (files whose name is
        README*, or whose path holds "result" or "lesson"/"lecon"/"learned"; md, txt, rst, json, yaml; limits in config.json
        "context" and "history") and writes context_candidates.json: for each candidate its id (C1...), class (n_periods,
        n_units, ic, cost, sharpe, sd), value, unit, file:line and a short excerpt. Deterministic. Exit 2 without
        project_dirs (nothing is read). The file is LOCAL: its excerpts never enter a request ([CONTEXT-LEAK]).
  confirm DIR --id C1 --name NAME [--role n|sd|base|effect|ic|cost|other] [--unit U]
        Copies the candidate into intake.json context.key_numbers (source "extracted", cited "file:line", confirmed true).
        The value is the candidate's: there is no way to type another one here.
  add DIR --name NAME --value V --by user|assumption [--role R] [--unit U]
        A number the user gave (confirmed) or the host assumed (not confirmed: sim.py does not use it).
  show DIR
        Prints the key numbers.
Roles: n (the number of independent periods or units the test can use), sd (noise of the outcome), base (a base rate);
without a role, the usual names n_periods, n_units, n, effectif, sd, std, base_rate are recognised.
Exit codes: 0 done, 1 refused, 2 usage error.

Usage: context.py extract|confirm|add|show DIR ...
Import: line_candidates(line), extract(work, intake) -> dict
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ written in the skill directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

EXTS = ('.md', '.txt', '.rst', '.json', '.yaml', '.yml')
ROLES = ('n', 'sd', 'base', 'effect', 'ic', 'cost', 'other')
NUM = r'(\d+(?:[.,]\d+)?)'
PERIOD_UNITS = r'(periods?|periodes?|trimestres?|quarters?|months?|mois|years?|ans|annees?|rebalancings?|rebalancements?)'
UNIT_NOUNS = r'(stocks?|titres?|firms?|entreprises?|companies|assets?|samples?|observations?|obs|securities)'
PATTERNS = (
    ('n_periods', re.compile(r'(?<![\w.,])%s\s*%s\b' % (NUM, PERIOD_UNITS)), 'unit'),
    ('n_periods', re.compile(r'\b(?:n_periods|nb_periods?|number of periods|nombre de periodes)\s*[:=]\s*(\d+)'), 'periods'),
    ('n_units', re.compile(r'\bn\s*=\s*(\d[\d,]*)'), 'units'),
    ('n_units', re.compile(r'(?<![\w.,])(\d[\d,]*)\s*%s\b' % UNIT_NOUNS), 'unit'),
    ('ic', re.compile(r'\b(?:rank[- ]?ic|ic|information coefficient)\b\s*(?:[:=]|of|de)?\s*(-?\d+[.,]\d+)'), ''),
    ('cost', re.compile(r'(?<![\w.,])%s\s*(bps|bp|basis points)\b' % NUM), 'unit'),
    ('cost', re.compile(r'(?:cost|cout|spread|fees|frais)\D{0,20}%s\s*%%' % NUM), '%'),
    ('sharpe', re.compile(r'sharpe\D{0,12}(-?\d+[.,]\d+)'), ''),
    ('sd', re.compile(r'(?:std|sd|ecart[- ]type|volatil\w*)\D{0,12}(\d+[.,]\d+)'), ''),
)


def _num(s):
    s = s.replace(',', '.') if re.fullmatch(r'\d+,\d{1,2}', s) else s.replace(',', '')
    v = float(s)
    return int(v) if v == int(v) and '.' not in s else v


def line_candidates(line):
    """[(class, value, unit)] found on one line (accents and case ignored)."""
    f = common.fold(line)
    out, seen = [], set()
    for cls, rx, unit in PATTERNS:
        for m in rx.finditer(f):
            try:
                v = _num(m.group(1))
            except ValueError:
                continue
            u = m.group(2) if unit == 'unit' and m.lastindex and m.lastindex >= 2 else unit
            if (cls, v) in seen:
                continue
            seen.add((cls, v))
            out.append((cls, v, u))
    return out


def wanted(rel):
    f = common.fold(rel)
    name = f.rsplit('/', 1)[-1]
    return name.startswith('readme') or any(k in f for k in ('result', 'lesson', 'lecon', 'learned'))


def project_dirs(intake):
    dirs = intake.get('project_dirs') if isinstance(intake, dict) else None
    return [d for d in dirs if isinstance(d, str) and d.strip()] if isinstance(dirs, list) else []


def extract(work, intake):
    cfg = common.config()
    ctx_cfg, hist = cfg['context'], cfg['history']
    ignore = set(hist.get('ignore_dirs') or [])
    cands, scanned, truncated = [], 0, False
    dirs = project_dirs(intake)
    for ri, d in enumerate(dirs):
        p = Path(d).expanduser()
        root = p if p.is_absolute() else Path(work) / p
        if not root.is_dir():
            raise ValueError('project folder not found: %s' % d)
        files = []
        for dp, dn, fn in os.walk(str(root)):
            dn[:] = sorted(x for x in dn if x not in ignore and not os.path.islink(os.path.join(dp, x)))
            for name in sorted(fn):
                full = Path(dp) / name
                rel = full.relative_to(root).as_posix()
                if full.suffix.lower() in EXTS and wanted(rel) and not full.is_symlink():
                    files.append((rel, full))
        for rel, full in sorted(files):
            if scanned >= ctx_cfg['max_files']:
                truncated = True
                break
            try:
                if full.stat().st_size > ctx_cfg['max_file_bytes']:
                    continue
                lines = full.read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n').split('\n')
            except OSError:
                continue
            scanned += 1
            for n, line in enumerate(lines, 1):
                for cls, v, u in line_candidates(line):
                    if len(cands) >= ctx_cfg['max_candidates']:
                        truncated = True
                        break
                    text = ' '.join(line.split())
                    cands.append({'id': 'C%d' % (len(cands) + 1), 'class': cls, 'value': v, 'unit': u or '', 'file': rel,
                                  'root': ri, 'line': n,
                                  'excerpt': text if len(text) <= ctx_cfg['max_excerpt_chars'] else text[:ctx_cfg['max_excerpt_chars'] - 3] + '...'})
    return {'stage': 'context', 'project_dirs': dirs, 'candidates': cands,
            'scan': {'files_scanned': scanned, 'truncated': truncated}}


def load_intake(work):
    p = Path(work) / 'intake.json'
    if not p.is_file():
        raise ValueError('no intake.json in %s' % work)
    return common.read_json(p)


def cmd_extract(a):
    work = Path(a.dir)
    intake = load_intake(work)
    if not project_dirs(intake):
        print('context.py: intake.json gives no project_dirs: nothing is read (ask the user for the folders of their '
              'project, or give the key numbers with "context.py add --by user")', file=sys.stderr)
        return 2
    out = extract(work, intake)
    common.write_json(work / 'context_candidates.json', out)
    if a.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        for c in out['candidates']:
            print('%s %-9s %s %s  %s:%d' % (c['id'], c['class'], c['value'], c['unit'], c['file'], c['line']))
        print('%d candidate(s) in %d file(s): confirm the ones that are true with "context.py confirm"'
              % (len(out['candidates']), out['scan']['files_scanned']))
    return 0


def _context(intake):
    ctx = intake.setdefault('context', {})
    ctx.setdefault('key_numbers', [])
    return ctx


def _put(ctx, entry):
    kns = ctx['key_numbers']
    for i, k in enumerate(kns):
        if isinstance(k, dict) and k.get('name') == entry['name']:
            kns[i] = entry
            return
    kns.append(entry)


def cmd_confirm(a):
    work = Path(a.dir)
    cp = work / 'context_candidates.json'
    if not cp.is_file():
        print('context.py: no context_candidates.json: run "context.py extract" first', file=sys.stderr)
        return 1
    cand = next((c for c in common.read_json(cp).get('candidates') or [] if c.get('id') == a.id), None)
    if cand is None:
        print('context.py: %s is not a candidate of context_candidates.json' % a.id, file=sys.stderr)
        return 1
    intake = load_intake(work)
    entry = {'name': a.name, 'value': cand['value'], 'source': 'extracted',
             'cited': '%s:%d' % (cand['file'], cand['line']), 'confirmed': True}
    unit = a.unit or cand.get('unit')
    if unit:
        entry['unit'] = unit
    if a.role:
        entry['role'] = a.role
    _put(_context(intake), entry)
    common.write_json(work / 'intake.json', intake)
    print(json.dumps(entry, ensure_ascii=False))
    return 0


def cmd_add(a):
    work = Path(a.dir)
    try:
        value = float(a.value)
    except ValueError:
        print('context.py: --value must be a number', file=sys.stderr)
        return 2
    value = int(value) if value == int(value) and '.' not in a.value else value
    intake = load_intake(work)
    entry = {'name': a.name, 'value': value, 'source': a.by, 'confirmed': a.by == 'user'}
    if a.unit:
        entry['unit'] = a.unit
    if a.role:
        entry['role'] = a.role
    _put(_context(intake), entry)
    common.write_json(work / 'intake.json', intake)
    print(json.dumps(entry, ensure_ascii=False))
    return 0


def cmd_show(a):
    intake = load_intake(Path(a.dir))
    for k in (intake.get('context') or {}).get('key_numbers') or []:
        print('%s = %s %s (%s%s%s)' % (k.get('name'), k.get('value'), k.get('unit', ''), k.get('source'),
                                       ', confirmed' if k.get('confirmed') else '',
                                       ', ' + k['cited'] if k.get('cited') else ''))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('extract')
    e.add_argument('dir')
    e.add_argument('--json', action='store_true')
    c = sub.add_parser('confirm')
    c.add_argument('dir')
    c.add_argument('--id', required=True)
    c.add_argument('--name', required=True)
    c.add_argument('--role', choices=ROLES)
    c.add_argument('--unit')
    d = sub.add_parser('add')
    d.add_argument('dir')
    d.add_argument('--name', required=True)
    d.add_argument('--value', required=True)
    d.add_argument('--by', required=True, choices=['user', 'assumption'])
    d.add_argument('--role', choices=ROLES)
    d.add_argument('--unit')
    s = sub.add_parser('show')
    s.add_argument('dir')
    a = ap.parse_args(argv)
    try:
        return {'extract': cmd_extract, 'confirm': cmd_confirm, 'add': cmd_add, 'show': cmd_show}[a.cmd](a)
    except ValueError as ex:
        print('context.py: %s' % ex, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
