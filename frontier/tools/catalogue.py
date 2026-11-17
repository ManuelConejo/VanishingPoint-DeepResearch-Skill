#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""OPTIONAL tool of Frontier: create and update a catalogue of methods for ONE domain (SKILL.md step 9). Frontier never needs
it: step 1-bis reads a catalogue only when one is configured (config.json "catalogue" or FRONTIER_CATALOGUE).

Standard library, no network of its own and no local copy of a bibliographic index: the works come from VP's gateway
(tools/gwclient.py, search-openalex of plugin cs-ai, no key required), with the date T of the run. It works on a laptop.

Division of labour. This tool PREPARES the batches of works (identifier, title, year, abstract) and CHECKS the format and the
score; the short record of each method (what it does, input and output, result, code, data, form, effort) is written by the
HOST language model, in an answers file next to each batch. Nothing the model writes can change the title, the year or the
score: they come from the batch and from the grid.

File format: the 12 columns of the reference methods table, tab-separated, one header line:
  question note id annee titre methode capacite entree_sortie resultat verif ampleur code
followed by 7 columns of the implementability score (grid fixed on 2026-11-12):
  score donnees transposable autre_usage forme verifiable effort
  score = max(donnees, transposable) x 2 + forme + verifiable + autre_usage - (0 faible, 1 moyen, 2 fort); maximum 14.
  donnees 0-3 (3 = every input is in public sources, 0 = a central input is absent without substitute), transposable 0-3,
  autre_usage 0-2, forme 0-3 (3 = code, 2 = pseudo-code or formula, 1 = described principle, 0 = vague), verifiable 0-3,
  effort faible | moyen | fort (heavy training, GPU, infrastructure; model calls are no obstacle). A work is EXCLUDED (not
  written) only when donnees = 0 and transposable <= 1. forme is MECHANICAL: 3 when "code" is a repository URL (github.com,
  gitlab.com, huggingface.co, zenodo.org, codeberg.org, bitbucket.org), else from the "form" word (pseudocode, formula,
  principle, vague). "note" is the host's 0-3 relevance of the work to the question (as in the reference table).
  Decision to review: the date of the last update lives in <catalogue>.meta.json, not in the table, so the table stays
  byte-compatible with the reference format.

Subcommands:
  create --domain D --out DIR --vp VPDIR [--query Q]... [--T YYYY-MM-DD] [--per-batch 10] [--n 50] [--question Q1]
        Runs "<domain> <query>" through the gateway for each query (default queries: method, algorithm), writes DIR/catalogue.tsv
        (header only), DIR/catalogue.meta.json and DIR/batches/batch-NNN.json (works with an "answers" file name and the
        fields the host must fill). Refuses an existing catalogue.
  ingest --catalogue FILE --batch batch-NNN.json [--answers FILE]
        Validates EVERY answer first (unknown or duplicate identifier, missing or extra field, a tab or a newline, a value
        outside its enumeration, a title or year typed by hand, an identifier already in the catalogue): one error and
        nothing is written. Then appends the rows with their computed score (excluded works are counted, not written). The
        "updated" date moves to the T of the run only when no batch is pending any more.
  update --catalogue FILE --vp VPDIR [--T YYYY-MM-DD]
        Incremental: the same queries again, keeping only the works dated AFTER "updated" (a work with a year only counts as
        31 December of that year) and absent from the catalogue; new batches continue the numbering. Nothing new: no batch,
        "updated" moves to T. Refused while batches are pending.
  check --catalogue FILE
        Format and score: the header, one row length, unique identifiers, every grid value in its range, the score recomputed
        from the grid, no excluded work written. Accepts the reference 12-column table. Exit 1 on a problem.
  status --catalogue FILE
        Prints the meta file.
Exit codes: 0 done, 1 refused or problem found, 2 usage error or VP not found.

Usage: catalogue.py create|ingest|update|check|status ...
Import: score(...), excluded(donnees, transposable), forme_from(code, form), read_rows(path)
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
import gwclient  # noqa: E402

RUN = 'frontier-catalogue'
COLS12 = ['question', 'note', 'id', 'annee', 'titre', 'methode', 'capacite', 'entree_sortie', 'resultat', 'verif', 'ampleur',
          'code']
EXTRA = ['score', 'donnees', 'transposable', 'autre_usage', 'forme', 'verifiable', 'effort']
EFFORT = {'faible': 0, 'low': 0, 'moyen': 1, 'medium': 1, 'fort': 2, 'high': 2}
EFFORT_FR = {'faible': 'faible', 'low': 'faible', 'moyen': 'moyen', 'medium': 'moyen', 'fort': 'fort', 'high': 'fort'}
FORMS = {'code': None, 'pseudocode': 2, 'formula': 2, 'principle': 1, 'vague': 0}
REPO_HOSTS = ('github.com', 'gitlab.com', 'huggingface.co', 'zenodo.org', 'codeberg.org', 'bitbucket.org')
TEXT_FIELDS = ['methode', 'capacite', 'entree_sortie', 'resultat', 'verif', 'ampleur']
ANSWER_KEYS = set(['id', 'note', 'code', 'donnees', 'transposable', 'autre_usage', 'form', 'verifiable', 'effort'] + TEXT_FIELDS)
FROM_BATCH = ('titre', 'annee', 'title', 'year', 'question', 'score', 'forme')


def _int_in(v, lo, hi, name):
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ValueError('%s must be an integer from %d to %d (found %r)' % (name, lo, hi, v))
    return v


def score(donnees, transposable, autre_usage, forme, verifiable, effort):
    """The implementability score of the grid (maximum 14)."""
    d = _int_in(donnees, 0, 3, 'donnees')
    t = _int_in(transposable, 0, 3, 'transposable')
    u = _int_in(autre_usage, 0, 2, 'autre_usage')
    f = _int_in(forme, 0, 3, 'forme')
    v = _int_in(verifiable, 0, 3, 'verifiable')
    if effort not in EFFORT:
        raise ValueError('effort must be faible, moyen or fort (found %r)' % (effort,))
    return max(d, t) * 2 + f + v + u - EFFORT[effort]


def excluded(donnees, transposable):
    return donnees == 0 and transposable <= 1


def forme_from(code, form):
    """forme (0-3), mechanically: 3 for a repository URL in `code`, else from the form word."""
    if form not in FORMS:
        raise ValueError('form must be one of %s (found %r)' % (', '.join(sorted(FORMS)), form))
    m = re.match(r'^https?://([^/\s]+)/', str(code or '').strip())
    if m and any(m.group(1).lower() == h or m.group(1).lower().endswith('.' + h) for h in REPO_HOSTS):
        return 3
    if form == 'code':
        raise ValueError('form "code" needs a repository URL in "code" (github.com, gitlab.com, huggingface.co ...)')
    return FORMS[form]


def read_rows(path):
    return common.read_tsv(path)


# ---------------------------------------------------------------- files


def meta_path(tsv):
    tsv = Path(tsv)
    return tsv.with_name(tsv.stem + '.meta.json')


def today():
    return datetime.date.today().isoformat()


def work_date(w):
    if w.get('date'):
        return w['date']
    return '%04d-12-31' % w['year'] if isinstance(w.get('year'), int) else None


def parse_works(gateway):
    out = []
    res = gateway.get('results')
    items = res if isinstance(res, list) else (res.get('results') or res.get('items') or []) if isinstance(res, dict) else []
    for d in items:
        if not isinstance(d, dict) or not isinstance(d.get('id'), str) or not isinstance(d.get('title'), str):
            continue
        date = str(d.get('date') or '')[:10]
        date = date if re.fullmatch(r'\d{4}-\d{2}-\d{2}', date) else None
        year = d.get('year') if isinstance(d.get('year'), int) else (int(date[:4]) if date else None)
        out.append({'id': d['id'], 'title': ' '.join(d['title'].split()), 'year': year, 'date': date,
                    'abstract': ' '.join(str(d.get('abstract') or '').split())})
    return out


def gather(vp, T, domain, queries, n, state, work=None, capped=None):
    """The works of every query. With `work` (a Frontier directory, --work) each request goes through the outgoing guard of
    tools/guards.py BEFORE the gateway is called. `capped`, a list, receives the queries whose answer reached n: the answer is
    cut at n (no pagination here), so works may be missing and `updated` must not be trusted to have moved past them."""
    plugin = common.config()['matter']['literature_plugin']
    seen, works = set(), []
    for q in queries:
        gw = gwclient.call(vp, T, RUN, state, plugin, 'search-openalex', '%s %s' % (domain, q), n, work=work)
        found = parse_works(gw)
        if capped is not None and len(found) >= n:
            capped.append(q)
        for w in found:
            if w['id'] not in seen:
                seen.add(w['id'])
                works.append(w)
    return works


INSTRUCTIONS = ('Write the answers file next to this batch (same name with .answers.json): a JSON list with one record per '
                'work: id (as in the batch), note 0-3 (relevance to the question), methode, capacite, entree_sortie, resultat, '
                'verif, ampleur (short texts, no tab or newline, read from the abstract or the paper), code (a repository URL or '
                'empty), form (code | pseudocode | formula | principle | vague), donnees 0-3, transposable 0-3, autre_usage 0-2, '
                'verifiable 0-3, effort (faible | moyen | fort). Never write the title, the year or the score.')


def write_batches(out_dir, works, per_batch, start, domain, question):
    names = []
    bdir = Path(out_dir) / 'batches'
    bdir.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(works), per_batch):
        k = start + i // per_batch
        name = 'batch-%03d.json' % k
        common.write_json(bdir / name, {'batch': k, 'domain': domain, 'question': question,
                                        'works': works[i:i + per_batch], 'answers': name.replace('.json', '.answers.json'),
                                        'instructions': INSTRUCTIONS})
        names.append(name)
    return names


def find_vp_or_fail(arg):
    vp = gwclient.find_vp(arg)
    if vp is None:
        raise ValueError('VP was not found (give --vp <dir>, or set FRONTIER_VP_DIR): the catalogue tool works through VP\'s gateway')
    return vp


# ---------------------------------------------------------------- commands


def cmd_create(a):
    out = Path(a.out)
    tsv = out / 'catalogue.tsv'
    if tsv.exists():
        print('catalogue.py: %s exists: use "update"' % tsv, file=sys.stderr)
        return 1
    vp = find_vp_or_fail(a.vp)
    queries = a.query or ['method', 'algorithm']
    T = a.T or today()
    out.mkdir(parents=True, exist_ok=True)
    capped = []
    works = gather(vp, T, a.domain, queries, a.n, out / 'state', work=a.work, capped=capped)
    if capped:
        print('catalogue.py: warning: %d quer(ies) reached the cap n = %d (no pagination): works may be missing; raise --n or '
              'narrow the queries (%s)' % (len(capped), a.n, '; '.join(capped)), file=sys.stderr)
    names = write_batches(out, works, a.per_batch, 1, a.domain, a.question)
    tsv.write_text('\t'.join(COLS12 + EXTRA) + '\n', encoding='utf-8')
    common.write_json(meta_path(tsv), {
        'version': 1, 'domain': a.domain, 'question': a.question, 'created': T, 'updated': None, 'last_work_date': None,
        'queries': queries, 'per_batch': a.per_batch, 'n': a.n, 'rows': 0, 'excluded': 0,
        'pending': {'T': T, 'batches': names}})
    print('%s: %d work(s) in %d batch(es) under %s; the host writes the answers files, then "ingest"'
          % (tsv, len(works), len(names), out / 'batches'))
    return 0


def validate_answers(answers, batch, known_ids):
    errs = []
    if not isinstance(answers, list):
        return ['the answers file must be a JSON list of records']
    by_id = {w['id']: w for w in batch['works']}
    seen = set()
    for i, rec in enumerate(answers):
        tag = 'answer %d' % (i + 1)
        if not isinstance(rec, dict):
            errs.append('%s: must be an object' % tag)
            continue
        wid = rec.get('id')
        tag = 'answer %s' % wid
        if wid not in by_id:
            errs.append('%s: not a work of the batch' % tag)
        if wid in seen:
            errs.append('%s: duplicate identifier' % tag)
        seen.add(wid)
        if wid in known_ids:
            errs.append('%s: already in the catalogue' % tag)
        for k in rec:
            if k in FROM_BATCH:
                errs.append('%s: %s is taken from the batch or computed, never written by hand' % (tag, k))
            elif k not in ANSWER_KEYS:
                errs.append('%s: unknown field %s' % (tag, k))
        for k in TEXT_FIELDS + ['code']:
            v = rec.get(k)
            if k == 'code' and v in (None, ''):
                continue
            if not isinstance(v, str) or not v.strip():
                errs.append('%s: %s must be a non-empty text' % (tag, k))
            elif re.search(r'[\t\r\n]', v):
                errs.append('%s: %s holds a tab or a newline' % (tag, k))
        try:
            _int_in(rec.get('note'), 0, 3, 'note')
            forme = forme_from(rec.get('code'), rec.get('form'))
            score(rec.get('donnees'), rec.get('transposable'), rec.get('autre_usage'), forme, rec.get('verifiable'),
                  rec.get('effort'))
        except ValueError as e:
            errs.append('%s: %s' % (tag, e))
    for wid in by_id:
        if wid not in seen:
            errs.append('answer %s: missing (every work of the batch needs a record; give a low grid to exclude it)' % wid)
    return errs


def cmd_ingest(a):
    tsv = Path(a.catalogue)
    mp = meta_path(tsv)
    if not tsv.is_file() or not mp.is_file():
        print('catalogue.py: %s or its meta file is missing' % tsv, file=sys.stderr)
        return 2
    meta = common.read_json(mp)
    bp = Path(a.batch)
    batch = common.read_json(bp)
    ap = Path(a.answers) if a.answers else bp.with_name(bp.name.replace('.json', '.answers.json'))
    if not ap.is_file():
        print('catalogue.py: no answers file %s (the host writes it)' % ap, file=sys.stderr)
        return 1
    answers = common.read_json(ap)
    known = {r.get('id') for r in read_rows(tsv)}
    errs = validate_answers(answers, batch, known)
    if errs:
        print('catalogue.py: refused, nothing written:')
        for e in errs:
            print('  ' + e)
        return 1
    by_id = {w['id']: w for w in batch['works']}
    lines, excl, last = [], 0, meta.get('last_work_date')
    for rec in answers:
        w = by_id[rec['id']]
        forme = forme_from(rec.get('code'), rec.get('form'))
        if excluded(rec['donnees'], rec['transposable']):
            excl += 1
            continue
        s = score(rec['donnees'], rec['transposable'], rec['autre_usage'], forme, rec['verifiable'], rec['effort'])
        cells = [meta.get('question', 'Q1'), str(rec['note']), w['id'], str(w['year'] or ''), w['title']] + \
                [rec[k] for k in TEXT_FIELDS[:3]] + [rec['resultat'], rec['verif'], rec['ampleur'], rec.get('code') or ''] + \
                [str(s), str(rec['donnees']), str(rec['transposable']), str(rec['autre_usage']), str(forme),
                 str(rec['verifiable']), EFFORT_FR[rec['effort']]]
        lines.append('\t'.join(c.replace('\t', ' ') for c in cells))
        d = work_date(w)
        if d and (last is None or d > last):
            last = d
    body = tsv.read_text(encoding='utf-8')
    if body and not body.endswith('\n'):
        body += '\n'
    tsv.write_text(body + ''.join(l + '\n' for l in lines), encoding='utf-8')
    meta['rows'] = meta.get('rows', 0) + len(lines)
    meta['excluded'] = meta.get('excluded', 0) + excl
    meta['last_work_date'] = last
    pend = meta.setdefault('pending', {'T': None, 'batches': []})
    pend['batches'] = [b for b in pend.get('batches') or [] if b != bp.name]
    if not pend['batches'] and pend.get('T'):
        meta['updated'] = pend['T']
        pend['T'] = None
    common.write_json(mp, meta)
    print('%s: %d row(s) added, %d excluded by the grid; %d batch(es) pending; updated %s'
          % (tsv, len(lines), excl, len(pend['batches']), meta.get('updated')))
    return 0


def cmd_update(a):
    tsv = Path(a.catalogue)
    mp = meta_path(tsv)
    if not tsv.is_file() or not mp.is_file():
        print('catalogue.py: %s or its meta file is missing: use "create"' % tsv, file=sys.stderr)
        return 2
    meta = common.read_json(mp)
    if (meta.get('pending') or {}).get('batches'):
        print('catalogue.py: refused: %d batch(es) are pending (%s): ingest them first'
              % (len(meta['pending']['batches']), ', '.join(meta['pending']['batches'])), file=sys.stderr)
        return 1
    vp = find_vp_or_fail(a.vp)
    T = a.T or today()
    known = {r.get('id') for r in read_rows(tsv)}
    since = meta.get('updated')
    capped = []
    works = gather(vp, T, meta['domain'], meta['queries'], meta.get('n', 50), tsv.parent / 'state', work=a.work, capped=capped)
    new = [w for w in works if w['id'] not in known and (since is None or (work_date(w) or '9999') > since)]
    if capped:
        meta['capped_queries'] = capped
        print('catalogue.py: warning: %d quer(ies) reached the cap n = %d (no pagination): newer works may be missing, so '
              '"updated" is not moved when nothing new is found (%s)' % (len(capped), meta.get('n', 50), '; '.join(capped)),
              file=sys.stderr)
    if not new:
        if capped:
            common.write_json(mp, meta)
            print('no new work since %s among the capped answers: "updated" stays at %s' % (since, since))
            return 0
        meta['updated'] = T
        meta['pending'] = {'T': None, 'batches': []}
        common.write_json(mp, meta)
        print('no new work since %s: nothing to ingest; updated set to %s' % (since, T))
        return 0
    bdir = tsv.parent / 'batches'
    nums = [int(m.group(1)) for p in bdir.glob('batch-*.json') for m in [re.match(r'batch-(\d+)\.json$', p.name)] if m]
    names = write_batches(tsv.parent, new, meta.get('per_batch', 10), (max(nums) if nums else 0) + 1, meta['domain'],
                          meta.get('question', 'Q1'))
    meta['pending'] = {'T': T, 'batches': names}
    common.write_json(mp, meta)
    print('%d new work(s) since %s in %d batch(es): %s' % (len(new), since, len(names), ', '.join(names)))
    return 0


def check_file(path):
    problems = []
    lines = [l for l in Path(path).read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n').split('\n')
             if l.strip() and not l.startswith('#')]
    if not lines:
        return ['empty file']
    head = lines[0].split('\t')
    if head[:12] != COLS12:
        problems.append('line 1: the first 12 columns must be %s' % ' '.join(COLS12))
        return problems
    has_extra = len(head) > 12
    if has_extra and head[12:] != EXTRA:
        problems.append('line 1: the columns after the 12 first must be %s' % ' '.join(EXTRA))
        return problems
    seen = set()
    for n, l in enumerate(lines[1:], 2):
        c = l.split('\t')
        if len(c) != len(head):
            problems.append('line %d: %d cells, the header has %d' % (n, len(c), len(head)))
            continue
        row = dict(zip(head, c))
        if row['id'] in seen:
            problems.append('line %d: duplicate id %s' % (n, row['id']))
        seen.add(row['id'])
        if row['annee'] and not re.fullmatch(r'\d{4}', row['annee']):
            problems.append('line %d: annee %r is not a year' % (n, row['annee']))
        if has_extra:
            try:
                d, t, u, f, v = (int(row[k]) for k in ('donnees', 'transposable', 'autre_usage', 'forme', 'verifiable'))
                got = int(row['score'])
                want = score(d, t, u, f, v, row['effort'])
            except ValueError as e:
                problems.append('line %d: %s' % (n, e))
                continue
            if got != want:
                problems.append('line %d: score %d but the grid gives %d (the score is computed, never written by hand)' % (n, got, want))
            if excluded(d, t):
                problems.append('line %d: an excluded work (donnees 0 and transposable <= 1) must not be written' % n)
    return problems


def cmd_check(a):
    probs = check_file(a.catalogue)
    for p in probs:
        print(p)
    if probs:
        return 1
    print('OK: %s (%d rows)' % (a.catalogue, len(read_rows(a.catalogue))))
    return 0


def cmd_status(a):
    print(json.dumps(common.read_json(meta_path(a.catalogue)), indent=2, ensure_ascii=False))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('create')
    c.add_argument('--domain', required=True)
    c.add_argument('--out', required=True)
    c.add_argument('--vp')
    c.add_argument('--query', action='append')
    c.add_argument('--T')
    c.add_argument('--per-batch', type=int, default=10)
    c.add_argument('--n', type=int, default=50)
    c.add_argument('--question', default='Q1')
    c.add_argument('--work', help='the Frontier directory of the idea: every request goes through its outgoing guard first')
    i = sub.add_parser('ingest')
    i.add_argument('--catalogue', required=True)
    i.add_argument('--batch', required=True)
    i.add_argument('--answers')
    u = sub.add_parser('update')
    u.add_argument('--catalogue', required=True)
    u.add_argument('--vp')
    u.add_argument('--T')
    u.add_argument('--work', help='the Frontier directory of the idea: every request goes through its outgoing guard first')
    k = sub.add_parser('check')
    k.add_argument('--catalogue', required=True)
    s = sub.add_parser('status')
    s.add_argument('--catalogue', required=True)
    a = ap.parse_args(argv)
    try:
        return {'create': cmd_create, 'ingest': cmd_ingest, 'update': cmd_update, 'check': cmd_check,
                'status': cmd_status}[a.cmd](a)
    except gwclient.GatewayError as e:
        print('catalogue.py: %s' % e, file=sys.stderr)
        return 1
    except (ValueError, OSError, KeyError) as e:
        print('catalogue.py: %s' % e, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
