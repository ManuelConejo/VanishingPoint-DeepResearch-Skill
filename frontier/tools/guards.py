#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Guards of Frontier round 3 (round-3 plan, lots 1 and 5, adjustments A2, A3, A4). Standard library, offline.

1. OUTGOING GUARD (A2). Nothing leaves the machine before this check passes: tools/gwclient.py calls check_outgoing() before
   it starts the gateway of VP, so a refusal is a refusal BEFORE sending (the plan's wording), not a control afterwards.
   What may leave is an explicit short list (ALLOWED_FORMS). The guard reads, locally, the project archives named in
   intake.json project_dirs, history.json, context_candidates.json and free_draft.md, and refuses:
     archive-passage  4 consecutive words of an archive, of the context candidates or of the free draft that are not words
                      of the idea;
     archive-word     a word that the archives hold and the idea does not (the SoftFold example), even alone, even when it
                      comes through intake.json query_terms;
     not-in-idea      (R3 directories) a word that is neither a word of the idea, its domain, a neighbouring idea, a
                      query_term, a kind word (code, dataset, benchmark ...), a number or a function word;
     too-long         more than MAX_QUERY_WORDS words;
     bad-repo-form    a repository that is not owner/name.
   A refusal is logged in matter/refused.jsonl with the SHA-256 of the text and the reason codes, never the text.
2. PROVENANCE (A3). The authority is AUTHORITY: the gateway journal written by VP. provenance() tells for a saved envelope
   whether the journal binds it: 'journal-attested' (an entry of the same run, T, call and query exists, no field of that
   entry contradicts the envelope, and a field that binds the CONTENT is present and equal: response_sha256, or index_total
   for a total), 'mismatch' (a field present in the journal differs from the envelope: the envelope was changed) or
   'unverified provenance' (nothing in the journal binds the content: shown as such, never as extracted).
3. COVERAGE (A4). coverage() counts what the journal of a VP run shows: calls, searches, calls that reached their result cap,
   sources that failed. It is NOT a recall: recall is "unknown" without an independent reference.

CLI:  guards.py check DIR "text" [--kind query|repo]      print the reasons, exit 1 when refused
      guards.py coverage-write DIR                        write prior_art.json coverage from the journal of the VP run "prior_art"
Import: check_outgoing(work, text, kind), provenance(work, rel), coverage(run_dir), not_found_note(cov), is_r3(work),
        response_digest(gateway), ALLOWED_FORMS, MAX_QUERY_WORDS, AUTHORITY
"""
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ written in the skill directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

MAX_QUERY_WORDS = 12
SHINGLE = 4
AUTHORITY = ('the gateway journal state/journal.jsonl written by VP (a local envelope is only a copy: it proves nothing '
             'alone); a value the journal does not bind is shown as "unverified provenance", never as extracted')
ALLOWED_FORMS = [
    'idea-terms query: at most %d words, each a word of the idea, of its domain, of a neighbouring idea, of intake.json '
    'query_terms, a kind word (code, dataset, benchmark, implementation, library, data), a number or a function word '
    '(R3 directories; every directory gets the archive checks below)' % MAX_QUERY_WORDS,
    'repository: owner/name and nothing else',
    'moment query: the same rules as an idea-terms query',
    'never: a passage of the project archives, of the free draft or of the context candidates, nor a word that the '
    'archives hold and the idea does not']
KIND_WORDS = frozenset('code dataset datasets benchmark benchmarks implementation implementations library libraries data '
                       'repository software tool tools open source method methods algorithm algorithms'.split())
FUNCTION = frozenset('''the and for with that this from into are was were has have had not but its their than then when
while also can may will would should which what where about over under between within without each such more most some any
all one two per via use used using only both either other another same these those there here they them very just like
because often of in on at to by as or is it be an a if so do does did how why who whom whose'''.split())
REPO = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
JOURNAL_KEYS = ('repos', 'datasets', 'models', 'spaces', 'items', 'results', 'hits')


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _read(p):
    try:
        return Path(p).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


def _json(p):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def is_r3(work):
    """True for a directory of round 3: intake.json frontier_version >= 3, or the marker written by new_run.py."""
    work = Path(work)
    it = _json(work / 'intake.json')
    if isinstance(it, dict) and isinstance(it.get('frontier_version'), int) and it['frontier_version'] >= 3:
        return True
    mk = _json(work / 'frontier-version.json')
    return isinstance(mk, dict) and isinstance(mk.get('frontier_version'), int) and mk['frontier_version'] >= 3


def _version(work):
    work = Path(work)
    it = _json(work / 'intake.json')
    if isinstance(it, dict) and isinstance(it.get('frontier_version'), int):
        return it['frontier_version']
    mk = _json(work / 'frontier-version.json')
    if isinstance(mk, dict) and isinstance(mk.get('frontier_version'), int):
        return mk['frontier_version']
    return 0


def is_v2(work):
    """True for a directory of Frontier v2: frontier_version >= 4 (intake.json, or the marker that tools/new_run.py writes).
    A v2 directory is also an R3 directory."""
    return _version(work) >= 4


def plan_vocabulary(work):
    """Words the host wrote in a research plan (research_plan.json fields and keywords; the search_plan of the neighbouring
    ideas): they widen the vocabulary a query may use. They never widen the archives' vocabulary: the archive-word rule
    looks at the words of the idea alone."""
    work = Path(work)
    texts = []

    def plan_texts(plan):
        for it in (plan.get('iterations') if isinstance(plan, dict) else None) or []:
            for f in (it.get('fields') if isinstance(it, dict) else None) or []:
                if isinstance(f, dict):
                    texts.append(str(f.get('field', '')))
                    texts.extend(k for k in f.get('keywords') or [] if isinstance(k, str))

    plan_texts(_json(work / 'research_plan.json'))
    for fname in ('rebound.json', 'rebound_after.json'):
        rb = _json(work / fname)
        for i in (rb.get('ideas') if isinstance(rb, dict) else None) or []:
            if isinstance(i, dict):
                plan_texts(i.get('search_plan'))
    return texts


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            for s in _strings(v):
                yield s
    elif isinstance(x, list):
        for v in x:
            for s in _strings(v):
                yield s


def _stem(w):
    return w[:-1] if len(w) > 4 and w.endswith('s') else w


def own_vocabulary(work):
    """Words the user's own idea justifies: idea, domain, query_terms, and the neighbouring ideas of the rebound files."""
    work = Path(work)
    it = _json(work / 'intake.json') or {}
    texts = [it.get('idea', ''), it.get('domain', '')] + [t for t in it.get('query_terms') or [] if isinstance(t, str)]
    texts += plan_vocabulary(work)
    for fname in ('rebound.json', 'rebound_after.json'):
        rb = _json(work / fname)
        for i in (rb.get('ideas') if isinstance(rb, dict) else None) or []:
            if isinstance(i, dict):
                texts += [str(i.get('title', '')), str((i.get('hypothesis') or {}).get('statement', '')),
                          str((i.get('mechanism') or {}).get('summary', ''))]
    words = set()
    for t in texts:
        for w in common.words(str(t)):
            words.add(w)
            words.add(_stem(w))
    return words


def idea_only_vocabulary(work):
    """The words of the idea and its domain alone (query_terms are not counted: they are written by the host)."""
    it = _json(Path(work) / 'intake.json') or {}
    words = set()
    for w in common.words('%s %s' % (it.get('idea', ''), it.get('domain', ''))):
        words.add(w)
        words.add(_stem(w))
    return words


def _archive_files(dirs):
    cfg = common.config()['history']
    exts = tuple('.' + e for e in cfg['extensions'])
    ignore = set(cfg['ignore_dirs'])
    n, total = 0, 0
    for d in dirs:
        root = Path(d).expanduser()
        if not root.is_dir():
            continue
        for p in sorted(root.rglob('*')):
            if n >= cfg['max_files'] or total >= cfg['max_total_bytes']:
                return
            if p.is_symlink() or not p.is_file() or p.suffix.lower() not in exts:
                continue
            if any(part in ignore for part in p.relative_to(root).parts):
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size > cfg['max_file_bytes']:
                continue
            n += 1
            total += size
            yield p


def local_secrets(work):
    """([(label, text)] archives and context candidates, [(label, text)] free draft): what must never leave."""
    work = Path(work)
    arch, draft = [], []
    it = _json(work / 'intake.json') or {}
    dirs = [d for d in it.get('project_dirs') or [] if isinstance(d, str) and d.strip()]
    for p in _archive_files(dirs):
        arch.append(('archive file', _read(p)))
    hist = _json(work / 'history.json')
    if hist is not None:
        for e in hist.get('entries') or [] if isinstance(hist, dict) else []:
            if isinstance(e, dict):
                for f in ('excerpt', 'verdict_excerpt', 'reopen_condition', 'file'):
                    if isinstance(e.get(f), str):
                        arch.append(('history.json', e[f]))
    cc = _json(work / 'context_candidates.json')
    if cc is not None:
        arch += [('context candidates', s) for s in _strings(cc)]
    fd = work / 'free_draft.md'
    if fd.is_file():
        draft.append(('free draft', _read(fd)))
    return arch, draft


def _windows(words, k):
    return {tuple(words[i:i + k]) for i in range(len(words) - k + 1)}


def check_outgoing(work, text, kind='query'):
    """Reason codes (a list of short strings, never the text) that refuse `text`; [] when it may leave."""
    work = Path(work)
    text = text if isinstance(text, str) else ''
    if kind == 'repo':
        return [] if REPO.match(text) and '..' not in text.split('/') else ['bad-repo-form']
    reasons = []
    words = common.words(text)
    if not words:
        return ['empty']
    if len(words) > MAX_QUERY_WORDS:
        reasons.append('too-long')
    own = own_vocabulary(work)
    idea = idea_only_vocabulary(work)
    arch, draft = local_secrets(work)
    own_windows = set()
    it = _json(work / 'intake.json') or {}
    own_windows |= _windows(common.words('%s %s' % (it.get('idea', ''), it.get('domain', ''))), SHINGLE)
    q_windows = _windows(words, SHINGLE) if len(words) >= SHINGLE else set()
    for label, bucket in (('archive-passage', arch), ('draft-passage', draft)):
        for _, body in bucket:
            hit = (q_windows & _windows(common.words(body), SHINGLE)) - own_windows
            if hit:
                reasons.append(label)
                break
    arch_vocab = set()
    for _, body in arch:
        arch_vocab.update(w for w in common.words(body) if len(w) >= 4 and w not in FUNCTION)
    for w in words:
        if len(w) >= 4 and w not in FUNCTION and w not in idea and _stem(w) not in idea and w in arch_vocab:
            reasons.append('archive-word')
            break
    if is_r3(work):
        for w in words:
            if (w in own or _stem(w) in own or w in KIND_WORDS or w in FUNCTION or w.isdigit() or len(w) <= 2):
                continue
            reasons.append('not-in-idea')
            break
    return sorted(set(reasons))


def log_refusal(work, text, kind, reasons):
    p = Path(work) / 'matter' / 'refused.jsonl'
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(str(p), 'a', encoding='utf-8') as f:
        f.write(json.dumps({'utc': utc_now(), 'kind': kind, 'sha256': hashlib.sha256(str(text).encode('utf-8')).hexdigest(),
                            'reasons': list(reasons)}) + '\n')


# ---------------------------------------------------------------- provenance


def response_digest(gateway):
    return hashlib.sha256(json.dumps(gateway, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()


def result_count(gateway):
    res = (gateway or {}).get('results')
    if isinstance(res, dict):
        for k in JOURNAL_KEYS:
            if isinstance(res.get(k), list):
                return len(res[k])
        return 1
    if isinstance(res, list):
        return len(res)
    return 1 if res else 0


def journal_entries(work):
    out = []
    for line in _read(Path(work) / 'matter' / 'state' / 'journal.jsonl').splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def provenance(work, rel):
    """(status, why) for the saved envelope <work>/<rel>: 'journal-attested' | 'mismatch' | 'unverified provenance'."""
    work = Path(work)
    env = _json(work / rel) if isinstance(rel, str) else None
    if not isinstance(env, dict) or not isinstance(env.get('gateway'), dict):
        return 'unverified provenance', 'the envelope is unreadable'
    gw = env['gateway']
    same = [e for e in journal_entries(work) if e.get('call') == env.get('command') and e.get('query') == env.get('arg')
            and e.get('T') == env.get('T') and e.get('run') == env.get('run')]
    if not same:
        return 'unverified provenance', 'no entry of the gateway journal matches this call'
    problems, bound = [], False
    for e in same:
        bad, binds = [], False
        if isinstance(e.get('count'), int) and e['count'] != result_count(gw):
            bad.append('count %s in the journal, %s in the envelope' % (e['count'], result_count(gw)))
        if 'index_total' in e and e['index_total'] != gw.get('index_total'):
            bad.append('index_total %r in the journal, %r in the envelope' % (e['index_total'], gw.get('index_total')))
        elif 'index_total' in e and e['index_total'] is not None:
            binds = True
        if 'response_sha256' in e:
            if e['response_sha256'] != response_digest(gw):
                bad.append('the response digest of the journal differs from the envelope')
            else:
                binds = True
        if not bad and binds:
            return 'journal-attested', ''
        if bad:
            problems.append('; '.join(bad))
        bound = bound or binds
    if problems and len(problems) == len(same):
        return 'mismatch', problems[0]
    return 'unverified provenance', 'the journal holds no digest or total that binds the content of this answer'


# ---------------------------------------------------------------- coverage


def coverage(run_dir):
    """What the gateway journal of a VP run shows about the search: observable coverage, never a recall."""
    entries = []
    for line in _read(Path(run_dir) / 'state' / 'journal.jsonl').splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get('call'):
            entries.append(e)
    searches = [e for e in entries if str(e.get('call')).startswith('search')]
    capped = [e for e in searches if not e.get('error') and isinstance(e.get('count'), int) and isinstance(e.get('n'), int)
              and e['n'] > 0 and e['count'] >= e['n']]
    down = sorted({str(e.get('engine') or str(e['call']).replace('search-', '')) for e in entries if e.get('error')})
    return {'calls': len(entries), 'searches': len(searches), 'caps_reached': len(capped), 'sources_unavailable': down,
            'recall': 'unknown', 'basis': 'gateway journal of the VP run; no independent reference, so no recall is estimated'}


def not_found_note(cov):
    weak = bool(cov.get('caps_reached')) or bool(cov.get('sources_unavailable'))
    if weak:
        why = []
        if cov.get('caps_reached'):
            why.append('%d call(s) reached their result cap' % cov['caps_reached'])
        if cov.get('sources_unavailable'):
            why.append('unavailable: %s' % ', '.join(cov['sources_unavailable']))
        return 'Not found is weak here (%s); it is never a proof of absence' % '; '.join(why)
    return 'Not found within this coverage only (%s call(s)); never a proof of absence' % cov.get('calls')


def coverage_line(cov):
    down = ', '.join(cov.get('sources_unavailable') or []) or 'none'
    return ('Coverage (observable, from the VP gateway journal): %d call(s) (%d search(es)), %d reached their result cap, '
            'sources unavailable: %s; recall unknown (no independent reference).' % (
                cov.get('calls', 0), cov.get('searches', 0), cov.get('caps_reached', 0), down))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('check')
    c.add_argument('dir')
    c.add_argument('text')
    c.add_argument('--kind', default='query', choices=['query', 'repo'])
    w = sub.add_parser('coverage-write')
    w.add_argument('dir')
    a = ap.parse_args(argv)
    if a.cmd == 'check':
        reasons = check_outgoing(a.dir, a.text, a.kind)
        print(json.dumps({'allowed': not reasons, 'reasons': reasons}))
        return 1 if reasons else 0
    work = Path(a.dir)
    it = _json(work / 'intake.json') or {}
    runs = (it.get('vp') or {}).get('runs') or {}
    pa = _json(work / 'prior_art.json')
    if not isinstance(runs.get('prior_art'), str) or not isinstance(pa, dict):
        print('guards.py: needs intake.json vp.runs.prior_art and prior_art.json', file=sys.stderr)
        return 2
    d = Path(runs['prior_art'])
    d = d if d.is_absolute() else work / d
    pa['coverage'] = coverage(d)
    common.write_json(work / 'prior_art.json', pa)
    print(json.dumps(pa['coverage']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
