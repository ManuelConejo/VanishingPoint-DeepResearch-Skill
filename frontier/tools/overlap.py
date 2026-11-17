#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Derive the prior-art overlap ledger from local VP journals and host assessments.

Usage: overlap.py DIR
Writes overlap_ledger.json deterministically; never searches or calls a model.
Query attribution uses only the returned identifiers in state/journal.jsonl.
Overlap judgments/dimensions come from closest_work; they are not inferred.
Import: derive(work, data=None), summary(ledger), report_lines(ledger).
"""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

FILES = ('intake.json', 'prior_art.json', 'rebound.json', 'rebound_after.json', 'run.json')
DIMENSIONS = ('problem', 'method', 'data', 'setting', 'claim')


def obj(value):
    return value if isinstance(value, dict) else {}


def items(value):
    return value if isinstance(value, list) else []


def filled(value):
    return isinstance(value, str) and not common.is_placeholder(value.strip(), 1)


def one_line(value):
    return ' '.join(str(value or '').split())


def read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8')), None
    except (OSError, ValueError, UnicodeError) as exc:
        return None, type(exc).__name__


def load_data(work):
    return {name: read(Path(work) / name)[0] for name in FILES if (Path(work) / name).exists()}


def norm_id(value):
    """Conservative normalization of common DOI/arXiv and repository identifiers."""
    s = one_line(value).lower()
    for prefix in ('https://doi.org/', 'http://doi.org/', 'http://dx.doi.org/', 'https://dx.doi.org/'):
        if s.startswith(prefix):
            return 'doi:' + s[len(prefix):]
    for prefix in ('https://arxiv.org/abs/', 'http://arxiv.org/abs/'):
        if s.startswith(prefix):
            return 'arxiv:' + s[len(prefix):]
    for prefix in ('https://github.com/', 'http://github.com/'):
        if s.startswith(prefix):
            return 'github:' + s[len(prefix):].rstrip('/')
    if s.startswith('10.') and '/' in s:
        return 'doi:' + s
    return s


def journal(path):
    """Keep physical line numbers; retain valid rows even when another row is bad."""
    rows, issues = [], []
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError):
        return [], ['journal unavailable']
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            issues.append('invalid JSON at line %d' % line_no)
            continue
        if not isinstance(row, dict) or not filled(row.get('call')):
            issues.append('invalid gateway entry at line %d' % line_no)
            continue
        rows.append((line_no, row))
    return rows, issues


def is_search(row):
    return str(row.get('call', '')).startswith('search') or row.get('call') in ('citing', 'references', 'related')


def sources(work, data):
    """Registered prior-art runs and local gateways, with all assessment scopes.

    A source is a journal, deduplicated by device/inode (aliases, hard links).
    Identical bytes in different journals still represent separate searches.
    """
    work = Path(work)
    runs = obj(obj(obj(data.get('intake.json')).get('vp')).get('runs'))
    groups = [('prior_art.json', obj(data.get('prior_art.json')), 'prior_art')]
    for name in ('rebound.json', 'rebound_after.json'):
        for idea in items(obj(data.get(name)).get('ideas')):
            pa = obj(obj(idea).get('prior_art'))
            groups.append(('%s:%s' % (name, obj(idea).get('id', '?')), pa, pa.get('vp_run')))
    paths, assessments, issues = {}, [], []

    def add_run(label):
        if not isinstance(label, str) or label in paths:
            return
        rel = runs.get(label)
        if not isinstance(rel, str):
            issues.append('%s: registered VP run unavailable' % label)
            return
        p = Path(rel)
        paths[label] = (p if p.is_absolute() else work / p) / 'state' / 'journal.jsonl'

    for name in sorted(runs):
        if name.startswith('prior_art'):
            add_run(name)
    for scope, pa, default_run in groups:
        if default_run in runs:
            add_run(default_run)
        elif scope == 'prior_art.json' and obj(obj(data.get('intake.json')).get('vp')).get('mode') == 'vp':
            add_run(default_run)
        for c in items(pa.get('closest_work')):
            c = obj(c)
            ref = obj(c.get('ref'))
            name = ref.get('run') or default_run
            add_run(name)
            assessments.append({'scope': scope, 'run': name, 'id': ref.get('id'), 'title': c.get('title'),
                                'kind': c.get('kind', 'paper'),
                                'dimensions': c.get('overlap_dimensions', []),
                                'difference': c.get('what_differs', '')})
    # Historical neighbours can be recorded only in run.json.
    for step in items(obj(data.get('run.json')).get('steps')):
        if obj(step).get('step') == 'rebound_vp_run':
            add_run(obj(step).get('vp_run'))
    for name in ('research', 'matter'):
        p = work / name / 'state' / 'journal.jsonl'
        if p.exists():
            # Internal labels cannot shadow a registered VP run with this name.
            paths['local:' + name] = p
    grouped = {}
    for label, path in sorted(paths.items()):
        try:
            st = path.stat()
            identity = (st.st_dev, st.st_ino)
        except OSError:
            identity = str(path.resolve())
        source = grouped.setdefault(identity, {'runs': [], 'path': path})
        source['runs'].append(label)
    return list(grouped.values()), assessments, issues


def derive(work, data=None):
    work = Path(work)
    data = load_data(work) if data is None else data
    srcs, assessments, issues = sources(work, data)
    if not isinstance(data.get('prior_art.json'), dict):
        issues.append('prior_art.json unavailable or unreadable: overlap assessments unknown')
    queries, linked = [], set()
    unknown_ids, partial_ids = {}, {}
    for source in srcs:
        labels = source['runs']
        label = ', '.join(labels)
        rows, bad = journal(source['path'])
        issues.extend('%s: %s' % (label, issue) for issue in bad)
        for line_no, row in rows:
            if not is_search(row):
                continue
            raw_ids = row.get('ids')
            ids = [i for i in raw_ids if filled(i)] if isinstance(raw_ids, list) else []
            complete = (isinstance(raw_ids, list) and len(ids) == len(raw_ids) and
                        not (not ids and isinstance(row.get('count'), int) and row['count'] > 0))
            if not complete:
                counts = partial_ids if ids else unknown_ids
                counts[label] = counts.get(label, 0) + 1
                if not ids:
                    ids = None
            if not filled(row.get('query')):
                issues.append('%s line %d: query text unknown' % (label, line_no))
            hits = []
            returned = {norm_id(i) for i in ids or []}
            for index, assessment in enumerate(assessments):
                # Local research/matter calls support main prior art as well as
                # neighbours. A registered run supports its own assessments only.
                local = any(s.startswith('local:') for s in labels)
                if norm_id(assessment['id']) in returned and (local or assessment['run'] in labels):
                    hits.append(dict(assessment))
                    linked.add(index)
            queries.append({'run': label, 'journal_line': line_no, 'call': row['call'],
                            'query': row.get('query', ''), 'returned_ids': ids,
                            'ids_complete': complete,
                            'error': row.get('error'), 'overlaps': hits})
    if unknown_ids or partial_ids:
        def counts_text(counts):
            return ', '.join('%s: %d' % item for item in sorted(counts.items())) or 'none'
        unknown, partial = sum(unknown_ids.values()), sum(partial_ids.values())
        issues.append('returned identifiers unknown or incomplete for %d queries: %d fully unknown (%s); '
                      '%d partial (%s); known IDs, per-query lines and errors retained in ledger' % (
                          unknown + partial, unknown, counts_text(unknown_ids), partial, counts_text(partial_ids)))
    unattributed = [dict(a) for i, a in enumerate(assessments) if i not in linked]
    for a in assessments:
        label = '%s %s' % (a['scope'], a['id'])
        if not filled(a['difference']):
            issues.append('%s: overlap lacks a stated difference' % label)
        dims = a['dimensions']
        if not isinstance(dims, list) or not dims or any(d not in DIMENSIONS for d in dims):
            issues.append('%s: state overlap_dimensions (problem/method/data/setting/claim)' % label)
    for a in unattributed:
        issues.append('%s %s: query attribution unknown' % (a['scope'], a['id']))
    if not srcs:
        issues.append('prior-art queries not checked: no available VP journal')
    return {'version': 1, 'query_count': len(queries),
            'overlap_count': len({norm_id(a['id']) for a in assessments if filled(a['id'])}),
            'overlap_occurrences': sum(len(q['overlaps']) for q in queries),
            'complete': not issues, 'queries': queries, 'unattributed_overlaps': unattributed,
            'closest_overlap': dict(assessments[0]) if assessments else None,
            'issues': issues,
            'basis': 'VP gateway journals join returned IDs to host closest_work assessments; no absence or novelty inference'}


def summary(ledger):
    closest = ledger['closest_overlap']
    text = ('%s (%s); difference: %s' % (closest['title'], closest['id'],
            closest['difference'] if filled(closest['difference']) else 'not stated [OVERLAP-LEDGER]')
            if closest else 'none assessed')
    return one_line('Overlap ledger: %d queries, %d overlaps (unique assessed works); closest: %s%s; detail: IDEA-REPORT.md' % (
        ledger['query_count'], ledger['overlap_count'], text,
        '; incomplete [OVERLAP-LEDGER]' if not ledger['complete'] else ''))


def report_lines(ledger):
    lines = ['## Prior-art overlap ledger', summary(ledger), ledger['basis'] + '.',
             'Overlap dimensions and differences are host assessments, not automatic verification. '
             'No assessed overlap for a returned item does not establish absence.']
    def overlap_line(a):
        dims = ', '.join(map(str, a['dimensions'])) if isinstance(a['dimensions'], list) else str(a['dimensions'])
        return '- Overlap [%s] %s (%s, %s), dimensions: %s; difference: %s' % (
            a['scope'], a['title'], a['id'], a['kind'], dims or 'not stated',
            a['difference'] if filled(a['difference']) else 'not stated [OVERLAP-LEDGER]')
    for q in ledger['queries']:
        returned = 'unknown' if q['returned_ids'] is None else ', '.join(q['returned_ids'])
        if q['returned_ids'] is not None and not q.get('ids_complete', True):
            returned += ' (incomplete)'
        lines.append('- Query %s:%s [%s]: %s; error: %s; returned IDs: %s' % (
            q['run'], q['journal_line'], q['call'], q['query'], q['error'] or 'none',
            returned))
        lines.extend(overlap_line(a) for a in q['overlaps'])
        if not q['overlaps']:
            lines.append('- No assessed overlap attributed to this query.')
    if ledger['unattributed_overlaps']:
        lines.append('Unattributed overlaps (no query hit inferred):')
        lines.extend(overlap_line(a) for a in ledger['unattributed_overlaps'])
    lines.extend('- [OVERLAP-LEDGER] ' + issue for issue in ledger['issues'])
    return [one_line(line) for line in lines]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('dir')
    a = ap.parse_args(argv)
    work = Path(a.dir)
    if not work.is_dir() or not (work / 'prior_art.json').is_file():
        ap.error('DIR must contain prior_art.json')
    ledger = derive(work)
    common.write_json(work / 'overlap_ledger.json', ledger)
    print(summary(ledger))
    return 0


if __name__ == '__main__':
    sys.exit(main())
