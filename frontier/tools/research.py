#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The iterative research plan of Frontier v2 (SKILL.md "Frontier v2: the path", stage 2; the plan-then-search-then-revise
loop is the one of the Nova system). Offline, standard library; every search goes through VP's gateway.

research_plan.json is written by the host: 2 to 3 iterations, each with the FIELDS to question (a discipline, why, keywords),
the works found, and a revision (what was learned, what changes in the next plan; the last iteration says why it stops);
then the outcome (Exists | Partially | Not found | Insufficient search, backed by a passage). This tool only does what must
not be typed by hand: the gateway calls (through the outgoing guard, BEFORE sending) and the coverage.

Subcommands (DIR = the working directory; --vp DIR when VP cannot be found by itself):
  search DIR --iteration N --field F --query Q [--n N] [--vp DIR]
      One gateway search with the date T of the idea. The query must use a keyword of field F as planned in iteration N
      (all the words of one keyword), and must pass the outgoing guard (tools/guards.py): a refusal sends nothing. The
      answer is saved (matter/gw-NNN.json), journaled by the gateway (research/state/journal.jsonl) and recorded in the
      iteration's "calls" with the ids of the works returned.
  coverage DIR
      Writes research_plan.json "coverage": calls, searches, result caps reached, sources unavailable, per iteration; the
      recall is unknown (no independent reference), never estimated. tools/check.py recomputes it ([PLAN-COVER]).
  status DIR
      Prints the coverage line and how weak a "Not found" would be.
Usage: research.py search|coverage|status DIR ...
Exit codes: 0 done, 1 refused, 2 usage error or VP not found.
Import: extract_ids(gateway), coverage_of(work, plan), words_of(text), keyword_used(query, keywords)
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ written in the skill directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import guards  # noqa: E402
import gwclient  # noqa: E402

RUN = 'frontier-research'


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def words_of(text):
    return set(common.words(str(text)))


def keyword_used(query, keywords):
    """True when all the words of at least one keyword are words of the query."""
    q = words_of(query)
    return any(words_of(k) and words_of(k) <= q for k in keywords if isinstance(k, str))


def extract_ids(gateway):
    """Identifiers of the works a gateway search answer returned, in order (tolerant of the shape of the items)."""
    res = (gateway or {}).get('results')
    items = res if isinstance(res, list) else (res.get('results') or res.get('items') or [] if isinstance(res, dict) else [])
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        for k in ('id', 'doi', 'arxiv', 'pmid'):
            v = it.get(k)
            if isinstance(v, str) and v.strip():
                out.append(v.strip() if k == 'id' else '%s:%s' % (k, v.strip()))
                break
    return out


def coverage_of(work, plan):
    """Observable coverage of the research calls: the gateway journal, and the calls per iteration. Never a recall."""
    cov = guards.coverage(Path(work) / 'research')
    cov['iterations'] = [{'n': it.get('n'), 'calls': len(it.get('calls') or []),
                          'fields': len([f for f in it.get('fields') or [] if isinstance(f, dict)])}
                         for it in (plan.get('iterations') if isinstance(plan, dict) else None) or [] if isinstance(it, dict)]
    return cov


def load_plan(work):
    p = Path(work) / 'research_plan.json'
    if not p.is_file():
        raise ValueError('no research_plan.json: write the plan (fields and keywords of iteration 1) first')
    return common.read_json(p)


def refuse(msg):
    print('research.py: refused: %s' % msg, file=sys.stderr)
    return 1


def cmd_search(a):
    work = Path(a.dir)
    try:
        plan = load_plan(work)
    except ValueError as e:
        return refuse(str(e))
    it = next((x for x in plan.get('iterations') or [] if isinstance(x, dict) and x.get('n') == a.iteration), None)
    if it is None:
        return refuse('iteration %s is not in research_plan.json' % a.iteration)
    field = next((f for f in it.get('fields') or [] if isinstance(f, dict) and f.get('field') == a.field), None)
    if field is None:
        return refuse('field %r is not planned in iteration %s' % (a.field, a.iteration))
    if not keyword_used(a.query, field.get('keywords') or []):
        return refuse('the query uses no keyword of the field %r as planned (all the words of one keyword): %s'
                      % (a.field, ' | '.join(str(k) for k in field.get('keywords') or [])))
    vp = gwclient.find_vp(a.vp)
    if vp is None:
        print('research.py: VP was not found (give --vp <dir>, or set FRONTIER_VP_DIR): the search goes through VP\'s gateway', file=sys.stderr)
        return 2
    cfg = common.config()
    T = common.read_json(work / 'intake.json')['T']
    plugin = cfg['matter'][cfg['research']['plugin_key']]
    command = cfg['research']['command']
    try:
        gw = gwclient.call(vp, T, RUN, work / 'research' / 'state', plugin, command, a.query, a.n or cfg['research']['max_results'],
                           work=work, kind='query')
    except gwclient.LeakRefused as e:
        return refuse(str(e))
    except gwclient.GatewayError as e:
        return refuse('the gateway: %s' % e)
    rel, sha = gwclient.save_envelope(work, command, a.query, T, plugin, RUN, gw)
    ids = extract_ids(gw)
    plan = load_plan(work)
    it = next(x for x in plan['iterations'] if x.get('n') == a.iteration)
    it.setdefault('calls', []).append({'field': a.field, 'query': a.query, 'command': command, 'envelope': rel,
                                       'envelope_sha256': sha, 'count': len(ids), 'ids': ids, 'utc': utc_now()})
    common.write_json(work / 'research_plan.json', plan)
    print(json.dumps({'envelope': rel, 'ids': ids}, ensure_ascii=False))
    return 0


def cmd_coverage(a):
    work = Path(a.dir)
    try:
        plan = load_plan(work)
    except ValueError as e:
        return refuse(str(e))
    plan['coverage'] = coverage_of(work, plan)
    common.write_json(work / 'research_plan.json', plan)
    print(json.dumps(plan['coverage'], ensure_ascii=False))
    return 0


def cmd_status(a):
    work = Path(a.dir)
    try:
        plan = load_plan(work)
    except ValueError as e:
        return refuse(str(e))
    cov = coverage_of(work, plan)
    print(guards.coverage_line(cov))
    print(guards.not_found_note(cov) + '.')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog='Usage: research.py search|coverage|status DIR ...')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('search')
    s.add_argument('dir')
    s.add_argument('--iteration', type=int, required=True)
    s.add_argument('--field', required=True)
    s.add_argument('--query', required=True)
    s.add_argument('--n', type=int)
    s.add_argument('--vp')
    for name in ('coverage', 'status'):
        sub.add_parser(name).add_argument('dir')
    a = ap.parse_args(argv)
    return {'search': cmd_search, 'coverage': cmd_coverage, 'status': cmd_status}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
