#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Matter and moment of Frontier (SKILL.md step 1-bis): existing code, datasets and benchmarks for the idea and for each
neighbouring idea, and a "moment" line (the subject rises, saturates, an old idea is revived). Standard library, no network of
its own: every search goes through VP's gateway (tools/gwclient.py), with the date T of the idea, and every answer is saved
under <dir>/matter/ (gw-NNN.json) with the gateway's own journal in matter/state/journal.jsonl. Licence and last activity of
a repository, and every publication total, are EXTRACTED from the saved answer, never typed: tools/check.py extracts them
again ([MAT-ENVELOPE], [MOMENT-*]).

Subcommands (DIR = the Frontier working directory; --vp DIR = the VP directory when it cannot be found by itself):
  search DIR --for main|N1.. --kind code|dataset|benchmark --query Q [--n N]
        One gateway command: code -> find-implementations (plugin code), dataset and benchmark -> search-hf-datasets
        (plugin cs-ai; the benchmark query gets the word "benchmark"; the plugins are config.json matter.*). Saves the
        answer, logs the search (matter/search-log.json) and prints the candidates (index, name, url, date, licence).
  repo DIR --for ID --repo owner/name
        repo-info of a named repository: its SPDX licence and its last activity BEFORE T (the last commit of the default
        branch at T; else a push date marked "as of now" when it is not after T; else unknown). Writes the item into
        material.json. Never a date after T.
  add DIR --for ID --kind dataset|benchmark --envelope matter/gw-NNN.json --candidate I
        An item for candidate I of a saved search (name, licence, date of the record when not after T).
  none DIR --for ID --kind code|dataset|benchmark
        Records "not found" for that idea and kind, with the queries searched (refused when nothing was searched).
        "Not found" is never a proof of absence.
  optional DIR [--for ID]
        The OPTIONAL local sources: the catalogue of methods (tools/catalogue.py format; config.json "catalogue" or
        FRONTIER_CATALOGUE) and the "directions" index (config.json "directions_index" or FRONTIER_DIRECTIONS_INDEX; TSV with
        a "direction" column and, when it has a "liste" column, only list A). Absent or unreadable: "skipped" with the
        reason, which the report says. Present: the rows whose words (5-letter stems) share at least matter.min_overlap with
        the idea. Never required.
  moment DIR --query Q [--years 5] [--engine openalex]
        Publication totals before T-5y ... T (one gateway call per date, the answer's index_total), the periods between
        them, and the reading rising | saturating | revived | unclear (thresholds: config.json "moment"). Writes moment.json.
  status DIR
        Which ideas have matter (an item or a recorded "not found" search).
Exit codes: 0 done, 1 refused (gateway refusal, nothing to record), 2 usage error or VP not found.

Usage: matter.py search|repo|add|none|optional|moment|status DIR ...
Import: moment_reading(rates, th), periods(series), extract_repo_info(gateway, T), extract_candidates(gateway),
        read_catalogue(path), read_directions(path)
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
import guards  # noqa: E402
import gwclient  # noqa: E402

RUN = 'frontier-matter'
KINDS = {'code': ('code_plugin', 'find-implementations', ''),
         'dataset': ('literature_plugin', 'search-hf-datasets', ''),
         'benchmark': ('literature_plugin', 'search-hf-datasets', ' benchmark')}
STOP = frozenset('''the and for with that this from into are was were has have had not but its their than then when while
also can may will would should which what where about over under between within without each such more most some any all
one two per via use used using only both either other another same these those there here they them very just like because
often'''.split())


# ---------------------------------------------------------------- extraction from a gateway answer


def _items(res):
    if isinstance(res, list):
        return [x for x in res if isinstance(x, dict)]
    if isinstance(res, dict):
        for k in ('repos', 'datasets', 'models', 'spaces', 'items', 'results', 'hits'):
            if isinstance(res.get(k), list):
                return [x for x in res[k] if isinstance(x, dict)]
    return []


def _licence_of(v):
    if isinstance(v, dict):
        v = v.get('spdx_id') or v.get('spdx') or v.get('key') or v.get('name')
    return v.strip() if isinstance(v, str) and v.strip() else None


def extract_candidates(gateway):
    """[{name, url, title, date, licence}] of the results of a search answer (tolerant of the shape of the items)."""
    out = []
    for d in _items((gateway or {}).get('results')):
        name = d.get('repo') or d.get('full_name') or d.get('id') or d.get('name')
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        url = d.get('url') if isinstance(d.get('url'), str) else None
        if url is None and re.fullmatch(r'[\w.-]+/[\w.-]+', name):
            url = 'https://github.com/' + name
        out.append({'name': name, 'url': url, 'title': d.get('title') if isinstance(d.get('title'), str) else None,
                    'date': (d.get('date') or d.get('published') or None), 'licence': _licence_of(d.get('licence') or d.get('license'))})
    return out


def extract_repo_info(gateway, T):
    """{licence, last_activity, last_activity_basis} of a repo-info answer; the date is never after T."""
    res = (gateway or {}).get('results')
    d = res if isinstance(res, dict) else (res[0] if isinstance(res, list) and res and isinstance(res[0], dict) else {})
    at = d.get('at_T') if isinstance(d.get('at_T'), dict) else {}
    lic = next((l for l in (_licence_of(at.get('licence')), _licence_of(at.get('license')), _licence_of(d.get('licence')),
                            _licence_of(d.get('license')), _licence_of(d.get('spdx')), _licence_of(d.get('spdx_id'))) if l), None)
    last, basis = None, 'unknown'
    day = str(at.get('date') or at.get('committer_date') or '')[:10]
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', day) and (not T or day <= T):
        last, basis = day, 'last commit before T'
    else:
        push = str(d.get('pushed_at') or '')[:10]
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', push) and (not T or push <= T):
            last, basis = push, 'push date (as of now)'
    return {'licence': lic or 'unknown', 'last_activity': last, 'last_activity_basis': basis}


# ---------------------------------------------------------------- moment


def _date(s):
    return datetime.date.fromisoformat(s)


def periods(series):
    """Periods between consecutive cumulative totals: [{from, to, count, per_year}] (per_year rounded to 2 decimals)."""
    out = []
    for a, b in zip(series, series[1:]):
        count = b['total'] - a['total']
        days = max(1, (_date(b['as_of']) - _date(a['as_of'])).days)
        out.append({'from': a['as_of'], 'to': b['as_of'], 'count': count, 'per_year': round(count / (days / 365.25), 2)})
    return out


def moment_reading(rates, th):
    """rising | saturating | revived | unclear from the yearly rates of the periods (oldest first); a pure function."""
    r = [float(x) for x in rates]
    if len(r) < 3 or sum(r) < th['min_total']:
        return 'unclear'
    p = max(range(len(r) - 1), key=lambda i: r[i])
    trough = min(r[p:])
    if p < len(r) - 2 and trough <= th['trough_ratio'] * r[p] and r[-1] >= th['revive_factor'] * max(trough, 1e-9):
        return 'revived'
    g1 = r[-1] / r[-2] if r[-2] > 0 else float('inf')
    g0 = r[-2] / r[-3] if r[-3] > 0 else float('inf')
    if g1 >= 1 + th['rise'] and g0 >= 1.0:
        return 'rising'
    if g1 < 1 + th['rise'] and max(r[:-1]) >= min(r) * (1 + th['rise']) and min(r) > 0:
        return 'saturating'
    return 'unclear'


def moment_line(reading, per, series, engine, query):
    rates = ', '.join('%g' % p['per_year'] for p in per)
    return ('Moment: %s: publications per year by period %s (%s index totals before %d dates read through VP\'s gateway, %s to %s, '
            'query "%s"); the counts describe the index, not the truth.' % (reading, rates, engine, len(series),
                                                                           series[0]['as_of'], series[-1]['as_of'], query))


# ---------------------------------------------------------------- optional local sources


def stems(text):
    return {w[:5] for w in common.words(text) if len(w) >= 4 and w not in STOP}


def read_catalogue(path):
    return common.read_tsv(path)


def read_directions(path):
    rows = common.read_tsv(path)
    if rows and 'liste' in rows[0]:
        rows = [r for r in rows if (r.get('liste') or '').strip().upper() == 'A']
    return rows


def _overlap(a, b):
    return len(stems(a) & stems(b))


def optional_entry(kind, conf, words, tgt, min_overlap, previous):
    """The optional_sources entry for the catalogue or the directions index; `previous` keeps the matches of other ideas."""
    flag = 'catalogue' if kind == 'catalogue' else 'directions index'
    var, key = (('FRONTIER_CATALOGUE', 'catalogue') if kind == 'catalogue' else ('FRONTIER_DIRECTIONS_INDEX', 'directions_index'))
    if not conf:
        return {'status': 'skipped', 'reason': 'not configured: set "%s" in config.json or %s (an optional local source, '
                                               'never required)' % (key, var)}
    p = Path(conf).expanduser()
    if not p.is_file():
        return {'status': 'skipped', 'reason': 'the configured %s %s is not a readable file' % (flag, conf)}
    keep = [m for m in (previous.get('matches') if isinstance(previous, dict) and previous.get('status') == 'used' else None) or []
            if isinstance(m, dict) and m.get('for') != tgt]
    found = []
    if kind == 'catalogue':
        for r in common.read_tsv(p):
            ov = _overlap(words, ' '.join(r.get(k, '') for k in ('titre', 'methode', 'capacite', 'entree_sortie')))
            if ov >= min_overlap:
                found.append((ov, r))
        found.sort(key=lambda x: (-x[0], -int(x[1].get('score') or 0) if str(x[1].get('score') or '').isdigit() else 0, x[1].get('id', '')))
        new = [{'for': tgt, 'id': r.get('id'), 'title': r.get('titre'), 'method': r.get('methode'), 'score': r.get('score') or None,
                'code': r.get('code') or None} for _, r in found[:5]]
    else:
        for r in read_directions(p):
            ov = _overlap(words, '%s %s' % (r.get('sujet', ''), r.get('direction', '')))
            if ov >= min_overlap:
                found.append((ov, r))
        found.sort(key=lambda x: (-x[0], x[1].get('annee', ''), x[1].get('direction', '')))
        new = [{'for': tgt, 'direction': r.get('direction'), 'annee': r.get('annee'), 'liste': r.get('liste'),
                'sujet': r.get('sujet'), 'source': r.get('source')} for _, r in found[:5]]
    return {'status': 'used', 'path': str(p.resolve()), 'matches': keep + new}


# ---------------------------------------------------------------- files


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def load_material(work):
    p = Path(work) / 'material.json'
    if p.exists():
        return common.read_json(p)
    return {'version': 1, 'generated_utc': utc_now(), 'items': [], 'searched': [], 'optional_sources': {}}


def idea_words(work, tgt):
    intake = common.read_json(Path(work) / 'intake.json')
    if tgt == 'main':
        return '%s %s' % (intake.get('idea', ''), intake.get('domain', ''))
    for fname in ('rebound.json', 'rebound_after.json'):
        p = Path(work) / fname
        if p.exists():
            for i in common.read_json(p).get('ideas') or []:
                if isinstance(i, dict) and i.get('id') == tgt:
                    return json.dumps([i.get('title'), (i.get('hypothesis') or {}).get('statement'),
                                       (i.get('mechanism') or {}).get('summary')], ensure_ascii=False)
    raise ValueError('%s is neither "main" nor an idea of a rebound file' % tgt)


def ensure_optional(work, mat, tgt='main', refresh=False):
    cfg = common.config()
    words = idea_words(work, tgt)
    opt = mat.setdefault('optional_sources', {})
    for kind, conf in (('catalogue', cfg.get('catalogue')), ('directions', cfg.get('directions_index'))):
        if refresh or kind not in opt:
            opt[kind] = optional_entry(kind, conf, words, tgt, cfg['matter']['min_overlap'], opt.get(kind))


def save_material(work, mat):
    mat['generated_utc'] = utc_now()
    common.write_json(Path(work) / 'material.json', mat)


def log_path(work):
    return Path(work) / 'matter' / 'search-log.json'


def load_log(work):
    p = log_path(work)
    return common.read_json(p) if p.exists() else []


def intake_T(work):
    return common.read_json(Path(work) / 'intake.json')['T']


def gateway_for(a, work):
    vp = gwclient.find_vp(a.vp)
    if vp is None:
        raise ValueError('VP was not found (give --vp <dir>, or set FRONTIER_VP_DIR): matter and moment come from VP\'s '
                         'gateway, so this step is skipped without VP; say so in the report')
    return vp


def call_gateway(a, work, plugin_key, cmd, arg, n=None, T=None):
    vp = gateway_for(a, work)
    T = T or intake_T(work)
    plugin = common.config()['matter'][plugin_key]
    gw = gwclient.call(vp, T, RUN, Path(work) / 'matter' / 'state', plugin, cmd, arg,
                       n or common.config()['matter']['max_candidates'], work=work,
                       kind='repo' if cmd == 'repo-info' else 'query')       # guarded BEFORE the call (round 3, A2)
    rel, sha = gwclient.save_envelope(work, cmd, arg, T, plugin, RUN, gw)
    return gw, rel, sha


def put_item(mat, item):
    for i, it in enumerate(mat['items']):
        if (it.get('for'), it.get('kind'), it.get('name')) == (item['for'], item['kind'], item['name']):
            mat['items'][i] = item
            return
    mat['items'].append(item)


# ---------------------------------------------------------------- commands


def cmd_search(a):
    work = Path(a.dir)
    plugin_key, cmd, suffix = KINDS[a.kind]
    idea_words(work, a.for_)                                       # refuses an unknown idea before any call
    query = a.query + suffix
    gw, rel, sha = call_gateway(a, work, plugin_key, cmd, query, a.n)
    cands = extract_candidates(gw)
    log = load_log(work)
    log.append({'for': a.for_, 'kind': a.kind, 'query': query, 'command': cmd, 'envelope': rel, 'envelope_sha256': sha,
                'candidates': len(cands)})
    common.write_json(log_path(work), log)
    print(json.dumps({'command': cmd, 'envelope': rel, 'candidates': [dict(c, index=i) for i, c in enumerate(cands)]},
                     ensure_ascii=False))
    return 0


def cmd_repo(a):
    work = Path(a.dir)
    idea_words(work, a.for_)
    T = intake_T(work)
    gw, rel, sha = call_gateway(a, work, 'code_plugin', 'repo-info', a.repo)
    info = extract_repo_info(gw, T)
    item = {'for': a.for_, 'kind': 'code', 'name': a.repo, 'url': 'https://github.com/' + a.repo, 'licence': info['licence'],
            'last_activity': info['last_activity'], 'last_activity_basis': info['last_activity_basis'], 'via': 'gateway',
            'command': 'repo-info', 'envelope': rel, 'envelope_sha256': sha}
    mat = load_material(work)
    put_item(mat, item)
    ensure_optional(work, mat)
    save_material(work, mat)
    print(json.dumps(item, ensure_ascii=False))
    return 0


def cmd_add(a):
    work = Path(a.dir)
    idea_words(work, a.for_)
    T = intake_T(work)
    if Path(a.envelope).is_absolute() or '..' in Path(a.envelope).parts or not (work / a.envelope).is_file():
        print('matter.py: %s is not a saved envelope of this directory' % a.envelope, file=sys.stderr)
        return 1
    env = common.read_json(work / a.envelope)
    cands = extract_candidates(env.get('gateway'))
    if not 0 <= a.candidate < len(cands):
        print('matter.py: the envelope has %d candidate(s), not %d' % (len(cands), a.candidate), file=sys.stderr)
        return 1
    c = cands[a.candidate]
    day = str(c.get('date') or '')[:10]
    dated = re.fullmatch(r'\d{4}-\d{2}-\d{2}', day) and day <= T
    item = {'for': a.for_, 'kind': a.kind, 'name': c['name'], 'url': c.get('url'), 'licence': c.get('licence') or 'unknown',
            'last_activity': day if dated else None, 'last_activity_basis': 'date of the record' if dated else 'unknown',
            'via': 'gateway', 'command': env.get('command', ''), 'envelope': a.envelope,
            'envelope_sha256': common.sha256_file(work / a.envelope)}
    mat = load_material(work)
    put_item(mat, item)
    ensure_optional(work, mat)
    save_material(work, mat)
    print(json.dumps(item, ensure_ascii=False))
    return 0


def cmd_none(a):
    work = Path(a.dir)
    idea_words(work, a.for_)
    done = [s for s in load_log(work) if s.get('for') == a.for_ and s.get('kind') == a.kind]
    if not done:
        print('matter.py: no search was made for %s (%s): search first; "not found" needs the queries that found nothing'
              % (a.for_, a.kind), file=sys.stderr)
        return 1
    if guards.is_r3(work) and any(s.get('candidates') for s in done):
        print('matter.py: the searches for %s (%s) returned candidates: "not found" is refused; record one with add or repo '
              '(Terra: a "none" cannot contradict the saved answers)' % (a.for_, a.kind), file=sys.stderr)
        return 1
    mat = load_material(work)
    mat['searched'] = [s for s in mat['searched'] if (s.get('for'), s.get('kind')) != (a.for_, a.kind)]
    mat['searched'].append({'for': a.for_, 'kind': a.kind, 'queries': [s['query'] for s in done], 'result': 'not found',
                            'envelope': done[-1]['envelope']})
    ensure_optional(work, mat)
    save_material(work, mat)
    print(json.dumps(mat['searched'][-1], ensure_ascii=False))
    return 0


def cmd_optional(a):
    work = Path(a.dir)
    mat = load_material(work)
    ensure_optional(work, mat, a.for_, refresh=True)
    save_material(work, mat)
    print(json.dumps(mat['optional_sources'], ensure_ascii=False))
    return 0


def shift_years(d, k):
    try:
        return d.replace(year=d.year - k)
    except ValueError:                                       # 29 February
        return d.replace(year=d.year - k, day=28)


def cmd_moment(a):
    work = Path(a.dir)
    T = _date(intake_T(work))
    if a.years < 3:
        print('matter.py: --years must be 3 or more', file=sys.stderr)
        return 2
    series = []
    for k in range(a.years, -1, -1):
        day = shift_years(T, k).isoformat()
        gw, rel, sha = call_gateway(a, work, 'literature_plugin', 'search-' + a.engine, a.query, 1, T=day)
        total = gw.get('index_total')
        if not isinstance(total, (int, float)):
            print('matter.py: the gateway gave no index_total for T %s (engine %s): no moment can be read from it'
                  % (day, a.engine), file=sys.stderr)
            return 1
        series.append({'as_of': day, 'total': total, 'envelope': rel, 'envelope_sha256': sha})
    th = {k: common.config()['moment'][k] for k in ('rise', 'revive_factor', 'trough_ratio', 'min_total')}
    per = periods(series)
    reading = moment_reading([p['per_year'] for p in per], th)
    out = {'version': 1, 'query': a.query, 'engine': a.engine, 'series': series, 'periods': per, 'reading': reading,
           'line': moment_line(reading, per, series, a.engine, a.query), 'thresholds': th, 'directions_note': None}
    if guards.is_r3(work):                  # round 3 (A3): which totals the gateway journal binds, which it does not
        states = [guards.provenance(work, s['envelope'])[0] for s in series]
        out['provenance'] = 'journal-attested' if all(s == 'journal-attested' for s in states) else 'unverified provenance'
        if out['provenance'] != 'journal-attested':
            out['line'] = out['line'].replace('Moment: %s:' % reading, 'Moment: %s (unverified provenance: the gateway journal does '
                                              'not bind these totals):' % reading, 1)
    common.write_json(work / 'moment.json', out)
    print(out['line'])
    return 0


def cmd_status(a):
    work = Path(a.dir)
    mat = load_material(work)
    ideas = ['main']
    for fname in ('rebound.json', 'rebound_after.json'):
        p = work / fname
        if p.exists():
            ideas += [i.get('id') for i in common.read_json(p).get('ideas') or [] if isinstance(i, dict)]
    have = {i.get('for') for i in mat['items']} | {s.get('for') for s in mat['searched'] if s.get('result') == 'not found'}
    print(json.dumps({'covered': [i for i in ideas if i in have], 'missing': [i for i in ideas if i not in have]}))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    def add(name):
        s = sub.add_parser(name)
        s.add_argument('dir')
        s.add_argument('--vp')
        return s
    s = add('search')
    s.add_argument('--for', dest='for_', required=True)
    s.add_argument('--kind', required=True, choices=sorted(KINDS))
    s.add_argument('--query', required=True)
    s.add_argument('--n', type=int)
    s = add('repo')
    s.add_argument('--for', dest='for_', required=True)
    s.add_argument('--repo', required=True)
    s = add('add')
    s.add_argument('--for', dest='for_', required=True)
    s.add_argument('--kind', required=True, choices=['dataset', 'benchmark'])
    s.add_argument('--envelope', required=True)
    s.add_argument('--candidate', required=True, type=int)
    s = add('none')
    s.add_argument('--for', dest='for_', required=True)
    s.add_argument('--kind', required=True, choices=sorted(KINDS))
    s = add('optional')
    s.add_argument('--for', dest='for_', default='main')
    s = add('moment')
    s.add_argument('--query', required=True)
    s.add_argument('--years', type=int, default=5)
    s.add_argument('--engine', default='openalex')
    add('status')
    a = ap.parse_args(argv)
    cmds = {'search': cmd_search, 'repo': cmd_repo, 'add': cmd_add, 'none': cmd_none, 'optional': cmd_optional,
            'moment': cmd_moment, 'status': cmd_status}
    try:
        return cmds[a.cmd](a)
    except gwclient.GatewayError as e:
        print('matter.py: %s' % e, file=sys.stderr)
        return 1
    except (ValueError, OSError, KeyError) as e:
        print('matter.py: %s' % e, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
