#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""V4 focused revision receipt and overlap marks. Offline; omissions never block.

The existing test grid, critic, fix proof and second critique retain their jobs.
This module checks one small host decision, not a new review or repair loop.
"""
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
import overlap
import schema_lite

SCHEMAS = Path(__file__).resolve().parent.parent / 'schemas'


def record(work, data, name):
    if name in data:
        return data[name], 'null record' if data[name] is None else None
    path = Path(work) / name
    if not path.exists():
        return None, None
    value, error = overlap.read(path)
    return value, error or ('null record' if value is None else None)


def visible(work, data):
    """Enable detailed card summaries with V3 fields or either V4 artifact.

    All formats receive visible checker marks and a complete report ledger.
    Writing either V4 artifact opts the card into both V4 summaries.
    """
    if any(name in data or (Path(work) / name).exists() for name in ('test_revision.json', 'overlap_ledger.json')):
        return True
    tj = overlap.obj(data.get('tests.json'))
    return 'prospective_not_applicable' in tj or any(
        any(k in t for k in ('pre_critique', 'start_action', 'readout_date')) or t.get('kind') == 'prospective' or
        any(k in overlap.obj(t.get('sensitivity')) for k in ('minimum_useful_effect', 'power_at_minimum'))
        for t in overlap.items(tj.get('tests')) if isinstance(t, dict))


def deciding(data):
    tj = overlap.obj(data.get('tests.json'))
    order = overlap.items(overlap.obj(tj.get('ranking')).get('order'))
    first = order[0] if order else None
    test = next((t for t in overlap.items(tj.get('tests')) if isinstance(t, dict) and t.get('id') == first), None)
    return first, test


def weaknesses(data):
    first, test = deciding(data)
    if test is None:
        return []
    return [(i, item) for i, item in enumerate(overlap.items(overlap.obj(data.get('critique.json')).get('items')))
            if isinstance(item, dict) and item.get('test') in (first, 'all') and overlap.filled(item.get('text'))]


def revision_problems(work, data):
    value, error = record(work, data, 'test_revision.json')
    if value is None:
        if error or weaknesses(data):
            return ['test_revision.json: %s; record one focused revision or no change with a reason' %
                    ('unreadable ' + error if error else 'deciding-test weakness has no receipt')]
        return []
    schema = common.read_json(SCHEMAS / 'test_revision.json')
    errors = schema_lite.validate(value, schema)
    if isinstance(value, dict) and isinstance(value.get('version'), bool):
        errors.append('version must be integer 1')
    if errors:
        return ['test_revision.json: ' + e for e in errors]
    first, test = deciding(data)
    if not test or value['test'] != first:
        return ['test_revision.json: test must be the deciding test, ranking.order[0]']
    index = value['critique_item']
    relevant = dict(weaknesses(data))
    if index not in relevant:
        errors.append('critique_item must name one weakness of the deciding test (or all)')
    for key in ('weakest_inference', 'reason'):
        if not overlap.filled(value[key]):
            errors.append('%s needs an explicit explanation' % key)
    retrieval = value['retrieval']
    if 'not_needed' in retrieval:
        if set(retrieval) != {'not_needed'} or not overlap.filled(retrieval['not_needed']):
            errors.append('retrieval needs either one search or not_needed with a reason')
    elif set(retrieval) == {'run', 'query'} and all(overlap.filled(v) for v in retrieval.values()):
        vp = overlap.obj(overlap.obj(data.get('intake.json')).get('vp'))
        rel = overlap.obj(vp.get('runs')).get(retrieval['run'])
        if vp.get('mode') != 'vp' or not isinstance(rel, str):
            errors.append('retrieval run must be registered in intake.json with VP enabled')
        else:
            path = Path(rel)
            path = path if path.is_absolute() else Path(work) / path
            rows, bad = overlap.journal(path / 'state' / 'journal.jsonl')
            searches = [r for _, r in rows if overlap.is_search(r)]
            if bad or len(searches) != 1 or searches[0].get('query') != retrieval['query']:
                errors.append('retrieval needs one dedicated VP run with exactly one matching search (reads allowed)')
    else:
        errors.append('retrieval needs one run/query or an explained not_needed')
    if value['decision'] == 'revised':
        for key in ('before', 'after'):
            if not overlap.filled(value.get(key)):
                errors.append('revised receipt needs %s summary' % key)
        if value.get('before') == value.get('after'):
            errors.append('before and after are identical; record no change with a reason instead')
    predictions = overlap.obj(value.get('predictions'))
    current = {p.get('hypothesis'): p for p in overlap.items(test.get('predictions')) if isinstance(p, dict)}
    ids = []
    for role in ('H1', 'H2', 'H0'):
        pred = overlap.obj(predictions.get(role))
        hid = pred.get('hypothesis')
        if not isinstance(hid, str) or hid not in current or pred != current.get(hid):
            errors.append('%s prediction must copy a current deciding-test prediction (any existing identifier may fill H0)' % role)
        if not overlap.filled(pred.get('direction')) or not overlap.filled(pred.get('unit')) or \
                not isinstance(pred.get('interval'), list) or len(pred['interval']) != 2:
            errors.append('%s needs explicit direction, interval and unit' % role)
        ids.append(hid)
    if any(ids[i] == ids[j] for i in range(3) for j in range(i)):
        errors.append('H1/H2/H0 must name three distinct hypotheses')
    return ['test_revision.json: ' + e for e in errors]


def revision_line(work, data):
    value, _ = record(work, data, 'test_revision.json')
    if not isinstance(value, dict):
        return 'Test revision: not recorded [REVISION]; detail: IDEA-REPORT.md' if weaknesses(data) else ''
    if value.get('decision') == 'no change':
        text = 'no change: %s' % value.get('reason', 'reason missing')
    else:
        text = '%s -> %s; why: %s' % (value.get('before', 'before missing'), value.get('after', 'after missing'),
                                    value.get('reason', 'reason missing'))
    return overlap.one_line('Test revision: %s; %s%s' % (
        value.get('test', '?'), text, '; incomplete [REVISION]' if revision_problems(work, data) else ''))


def revision_report(work, data):
    value, error = record(work, data, 'test_revision.json')
    lines = ['## Focused test revision', revision_line(work, data)]
    if value is not None:
        lines.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
    lines.extend('- [REVISION] ' + e for e in revision_problems(work, data))
    return lines


def run(work, data, problems, warnings):
    """Always append marks, in every directory version. No V4 methodology veto."""
    warnings.extend('mark: [REVISION] ' + e for e in revision_problems(work, data))
    if not isinstance(data.get('prior_art.json'), dict):
        return
    ledger = overlap.derive(work, data)
    warnings.extend('mark: [OVERLAP-LEDGER] ' + issue for issue in ledger['issues'])
    saved, error = record(work, data, 'overlap_ledger.json')
    if error or (saved is not None and saved != ledger):
        warnings.append('mark: [OVERLAP-LEDGER] saved ledger unreadable or stale; rerun tools/overlap.py DIR')
