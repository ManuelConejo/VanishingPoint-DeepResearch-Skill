#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Step "Already tried here" (SKILL.md, step 0-bis): search the user's OWN project archives for what was already tried.

LOCAL ONLY. This tool reads text files in the folders the user named (intake.json "project_dirs") and writes history.json
in the working directory. It opens no network connection, starts no process and sends nothing anywhere: what it finds
stays on this machine and never enters a request of VP or any command that reaches the network (SKILL.md, permanent rule
"Project archives"; tools/check.py [HISTORY-LEAK] checks it). It only searches and extracts: the terms (words of the idea,
hypotheses, tests and neighbouring ideas, with the synonyms the host model adds) and the final decision stay with the host.

Usage:
  history.py scan DIR --label intake|tests|rebound (--terms-file FILE | --term "name=syn1|syn2" ...) [--project-dir P ...]
                      [--group idea|hypothesis|test|neighbour] [--for ID]

  DIR            the Frontier working directory; history.json is written there. The folders to read are the --project-dir
                 arguments, else intake.json "project_dirs" (relative paths are taken from DIR).
  --label        which step the terms come from: intake (after step 0), tests (step 3: every term carries "for" = the test
                 id), rebound (step 8: every term carries "for" = the idea id). A rerun of a label replaces that label's
                 query and keeps the others; the entries are recomputed from the union of the queries, and an entry (file,
                 line) keeps its identifier E<n>.
  --terms-file   JSON {"terms": [{"term": "softfold", "synonyms": ["soft fold", "FOLD"], "group": "test",
                 "for": "T2", "generic": false}]}. "generic": true marks a word of the idea too broad to count as an overlap
                 with a test (it is listed on the card).

What is read: md, txt, rst, py, json, yaml, yml files (config.json "history": extensions), without .git, venv, node_modules and the
other ignored folders, without symbolic links, without binary files (a NUL byte), within the limits of config.json "history"
(max_files, max_file_bytes, max_total_bytes, max_entries_per_file). Matching ignores case and accents and respects word
limits. For every matching line, history.json holds an entry: file, line, a short excerpt, the terms found, the verdict markers
of the passage (French and English), the verdict (classed: CLASSE, NE PAS ROUVRIR, NON ADOPTE, NO-GO, NE PAS INTEGRER, REJECTED,
DO NOT REOPEN, ne JAMAIS re-proposer...; tried: verdict, tested, already tried, teste...; none) and the reopening condition when
one is written. The passage is the paragraph, bullet or table of the line (a window of lines in code files); when the term
is in the path of the file, on its first line or in a heading among its first lines, the verdict markers of the head of the
file apply too.
A search that finds nothing is not a proof that nothing was tried.

Exit code 0 = written; 1 = a project folder cannot be read (nothing written); 2 = usage error.
"""
import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ written in the skill directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

HISTORY = 'history.json'
LABELS = ('intake', 'tests', 'rebound')
GROUPS = ('idea', 'hypothesis', 'test', 'neighbour')
DEFAULT_GROUP = {'intake': 'idea', 'tests': 'test', 'rebound': 'neighbour'}
NEEDS_FOR = ('tests', 'rebound')
TEXT_EXT = ('md', 'txt', 'rst')
NOTE = ('Local search of the project archives only; nothing here was sent anywhere. A search that finds nothing is not a '
        'proof that nothing was tried: read the files found, and widen the terms and synonyms when in doubt.')

# Verdict markers, French and English. ASCII source: accents are written as \u escapes.
_I = re.I
STRONG = [
    re.compile(r'\bCLASSE[ES]?\b'),                      # upper case, accent dropped (CLASSE)
    re.compile(r'\bclass\xe9e?s?\b', _I),              # classe + acute e (the common noun "classe" is not a marker)
    re.compile(r'\bclassed\b', _I),
    re.compile(r'\bne\s+pas\s+r\xe9?ouvrir\b', _I),
    re.compile(r'\bne\s+jamais\s+re-?proposer\b', _I),
    re.compile(r'\bnon[\s-]adopt\xe9e?s?\b', _I),
    re.compile(r'\bnot\s+adopted\b', _I),
    re.compile(r'\bno[\s-]?go\b', _I),
    re.compile(r'\bne\s+pas\s+int\xe9grer\b', _I),
    re.compile(r'\bdo\s+not\s+integrate\b', _I),
    re.compile(r'\brejected\b', _I),
    re.compile(r'\brejet\xe9e?s?\b', _I),
    re.compile(r"\bdo(?:n't|\s+not)\s+re-?open\b", _I),
    re.compile(r'\bnever\s+re-?(?:propose|suggest)\b', _I),
]
WEAK = [
    re.compile(r'\bverdicts?\b', _I),
    re.compile(r'\btested\b', _I),
    re.compile(r'\btried\b', _I),
    re.compile(r'\balready\s+tried\b', _I),
    re.compile(r'\btest\xe9e?s?\b', _I),
    re.compile(r'\bessay\xe9e?s?\b', _I),
    re.compile(r'\bd\xe9j\xe0\s+(?:essay|test|tent)\xe9e?s?\b', _I),
    re.compile(r'\br\xe9fut\xe9e?s?\b', _I),
    re.compile(r'\brefuted\b', _I),
]
REOPEN = [
    re.compile(r'\br\xe9ouverture\s+conditionnelle\b', _I),
    re.compile(r'\bconditions?\s+de\s+r\xe9ouverture\b', _I),
    re.compile(r'\br\xe9ouverture\s+(?:si|quand|apr\xe8s|seulement)\b', _I),
    re.compile(r'\brouvrir\s+(?:seulement\s+|uniquement\s+)?(?:si|quand|apr\xe8s)\b', _I),
    re.compile(r'\bre-?open(?:ing)?\s+(?:only\s+)?(?:if|when|unless|once|after)\b', _I),
    re.compile(r'\bre-?opening\s+conditions?\b', _I),
    re.compile(r'\bconditional\s+re-?opening\b', _I),
]
BULLET = re.compile(r'^\s*(?:[-*+]|\d+[.)])\s+')
HEADING = re.compile(r'^\s{0,3}#{1,6}\s')


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def line_markers(line):
    """[(position, matched text, kind)] of the verdict markers of one line, kind 'strong' or 'weak'."""
    out = []
    for kind, pats in (('strong', STRONG), ('weak', WEAK)):
        for p in pats:
            for m in p.finditer(line):
                out.append((m.start(), m.group(0), kind))
    out.sort()
    return out


def reopen_in(line):
    return any(p.search(line) for p in REOPEN)


def clip_around(line, pos, n):
    line = line.strip()
    if len(line) <= n:
        return line
    start = max(0, min(pos, len(line) - n))
    return line[start:start + n].strip()


def block_ranges(lines, max_len):
    """For every line, the (first, last) index of its paragraph, bullet, heading or table; None for blank lines."""
    n = len(lines)
    ranges = [None] * n
    i = 0
    while i < n:
        if not lines[i].strip():
            i += 1
            continue
        end = i
        if not HEADING.match(lines[i]):
            while (end + 1 < n and lines[end + 1].strip() and not HEADING.match(lines[end + 1])
                   and not BULLET.match(lines[end + 1]) and end + 1 - i < max_len):
                end += 1
        for j in range(i, end + 1):
            ranges[j] = (i, end)
        i = end + 1
    return ranges


class Term:
    """One query term: canonical name, synonyms, compiled patterns, and where it comes from."""

    def __init__(self, label, raw):
        self.label = label
        self.term = raw['term']
        self.synonyms = raw.get('synonyms') or []
        self.generic = bool(raw.get('generic'))
        self.for_id = raw.get('for')
        self.patterns = [(v, common.term_pattern(v)) for v in [self.term] + list(self.synonyms)]
        self.patterns = [(v, p) for v, p in self.patterns if p is not None]


def normalise_terms(raw, label):
    """Validated term dicts (usage error -> ValueError)."""
    items = raw.get('terms') if isinstance(raw, dict) else raw
    if not isinstance(items, list) or not items:
        raise ValueError('no term given (a non-empty list of terms is required)')
    out = []
    for i, t in enumerate(items):
        if not isinstance(t, dict) or not isinstance(t.get('term'), str) or not t['term'].strip():
            raise ValueError('terms[%d]: "term" must be a non-empty string' % i)
        if common.term_pattern(t['term']) is None:
            raise ValueError('terms[%d]: %r has no word to search' % (i, t['term']))
        syn = t.get('synonyms', [])
        if not isinstance(syn, list) or not all(isinstance(s, str) and s.strip() for s in syn):
            raise ValueError('terms[%d]: "synonyms" must be a list of non-empty strings' % i)
        group = t.get('group', DEFAULT_GROUP[label])
        if group not in GROUPS:
            raise ValueError('terms[%d]: "group" must be one of %s' % (i, ', '.join(GROUPS)))
        if 'generic' in t and not isinstance(t['generic'], bool):
            raise ValueError('terms[%d]: "generic" must be true or false' % i)
        n = {'term': t['term'].strip(), 'synonyms': [s.strip() for s in syn], 'group': group}
        if label in NEEDS_FOR:
            if not isinstance(t.get('for'), str) or not t['for'].strip():
                raise ValueError('terms[%d]: a "%s" query needs "for" on every term (the id of the %s it is about)'
                                 % (i, label, 'test' if label == 'tests' else 'idea'))
        if isinstance(t.get('for'), str) and t['for'].strip():
            n['for'] = t['for'].strip()
        elif 'for' in t:
            raise ValueError('terms[%d]: "for" must be a non-empty string' % i)
        if t.get('generic') is True:
            n['generic'] = True
        out.append(n)
    return out


def parse_cli_term(spec, label, group, for_id):
    name, _, syn = spec.partition('=')
    t = {'term': name.strip(), 'synonyms': [s.strip() for s in syn.split('|') if s.strip()]}
    if group:
        t['group'] = group
    if for_id:
        t['for'] = for_id
    return t


# ---------------------------------------------------------------- scanning


def file_entries(root_key, rel, text, terms, cfg):
    """Entries (dicts without identifier) of one file, in line order."""
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    mdlike = rel.rsplit('.', 1)[-1].lower() in TEXT_EXT
    ranges = block_ranges(lines, cfg['max_block_lines']) if mdlike else None
    path_f = common.fold(rel)
    head_n = min(len(lines), cfg['file_verdict_lines'])
    head_marks = None
    entries = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        f = common.fold(line)
        hit_terms, matched, first_pos = [], [], None
        for t in terms:
            for variant, pat in t.patterns:
                m = pat.search(f)
                if m:
                    if t not in hit_terms:
                        hit_terms.append(t)
                    s = line[m.start():m.end()]
                    if s not in matched:
                        matched.append(s)
                    first_pos = m.start() if first_pos is None else min(first_pos, m.start())
        if not hit_terms:
            continue
        # passage of the line
        if mdlike:
            start, end = ranges[i] if ranges[i] else (i, i)
        else:
            start, end = max(0, i - cfg['window_lines']), min(len(lines) - 1, i + cfg['window_lines'])
        marks, reopen_at = [], None
        for j in range(start, end + 1):
            for pos, m, kind in line_markers(lines[j]):
                marks.append((j, pos, m, kind))
            if reopen_at is None and reopen_in(lines[j]):
                reopen_at = j
        # the verdict of the head of the file applies when the term names the file (path) or its title (line 1, or a heading
        # among the first lines): not to any line of a short file (a bullet of a lessons file is its own passage)
        in_head = (i == 0 or (i < cfg['title_lines'] and bool(HEADING.match(line)))
                   or any(p.search(path_f) for t in hit_terms for _, p in t.patterns))
        if in_head:
            if head_marks is None:
                head_marks = ([(j, pos, m, kind) for j in range(head_n) for pos, m, kind in line_markers(lines[j])],
                              next((j for j in range(head_n) if reopen_in(lines[j])), None))
            have = {(j, pos) for j, pos, _, _ in marks}
            marks += [x for x in head_marks[0] if (x[0], x[1]) not in have]
            if reopen_at is None:
                reopen_at = head_marks[1]
        strong = sorted([x for x in marks if x[3] == 'strong'], key=lambda x: (x[0], x[1]))
        weak = sorted([x for x in marks if x[3] == 'weak'], key=lambda x: (x[0], x[1]))
        names = []
        for x in strong + weak:
            if x[2] not in names:
                names.append(x[2])
        verdict = 'classed' if strong else ('tried' if weak else 'none')
        vline = (strong or weak or [None])[0]
        canon = []
        for t in terms:
            if t in hit_terms and t.term not in canon:
                canon.append(t.term)
        entry = {
            'root': root_key, 'file': rel, 'line': i + 1,
            'excerpt': clip_around(line, first_pos or 0, cfg['max_excerpt_chars']),
            'terms': canon, 'matched': matched,
            'labels': [lb for lb in LABELS if any(t.label == lb for t in hit_terms)],
            'for': sorted({t.for_id for t in hit_terms if t.for_id}),
            'verdict': verdict, 'markers': names,
            'verdict_line': vline[0] + 1 if vline else None,
            'verdict_excerpt': clip_around(lines[vline[0]], vline[1], cfg['max_excerpt_chars']) if vline else None,
            'reopen_condition': (lines[reopen_at].strip()[:cfg['max_condition_chars']]
                                 if reopen_at is not None else None),
            'reopen_line': reopen_at + 1 if reopen_at is not None else None,
        }
        entries.append(entry)
    return entries


def walk_files(root, cfg, stats):
    """Yield (relative posix path, path) of the candidate text files of a folder, in a fixed order; counts what is skipped."""
    ignore = set(cfg['ignore_dirs'])
    exts = {e.lower().lstrip('.') for e in cfg['extensions']}
    for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False):
        keep = []
        for d in sorted(dirnames):
            if d in ignore:
                continue
            if os.path.islink(os.path.join(dirpath, d)):
                stats['files_skipped']['link'] += 1
                continue
            keep.append(d)
        dirnames[:] = keep
        for name in sorted(filenames):
            p = os.path.join(dirpath, name)
            if os.path.islink(p):
                stats['files_skipped']['link'] += 1
                continue
            ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
            if ext not in exts:
                stats['files_skipped']['extension'] += 1
                continue
            yield Path(os.path.relpath(p, str(root))).as_posix(), p


def scan(roots, queries, cfg):
    """Scan the folders for the terms of all queries. roots: [(key, resolved path)]; queries: [(label, [term dict])].
    Returns (scan stats, entries without identifiers)."""
    terms = [Term(label, t) for label, ts in queries for t in ts]
    stats = {'files_scanned': 0, 'files_skipped': {'binary': 0, 'extension': 0, 'too_large': 0, 'link': 0, 'unreadable': 0},
             'bytes_scanned': 0, 'truncated': False, 'entries_capped': 0}
    entries = []
    stop = False
    for key, root in roots:
        if stop:
            break
        for rel, p in walk_files(root, cfg, stats):
            try:
                size = os.path.getsize(p)
            except OSError:
                stats['files_skipped']['unreadable'] += 1
                continue
            if size > cfg['max_file_bytes']:
                stats['files_skipped']['too_large'] += 1
                continue
            if stats['files_scanned'] >= cfg['max_files'] or stats['bytes_scanned'] + size > cfg['max_total_bytes']:
                stats['truncated'] = True
                stop = True
                break
            try:
                with open(p, 'rb') as f:
                    data = f.read()
            except OSError:
                stats['files_skipped']['unreadable'] += 1
                continue
            if b'\x00' in data:
                stats['files_skipped']['binary'] += 1
                continue
            stats['files_scanned'] += 1
            stats['bytes_scanned'] += len(data)
            found = file_entries(key, rel, data.decode('utf-8', 'replace'), terms, cfg)
            if len(found) > cfg['max_entries_per_file']:
                stats['entries_capped'] += len(found) - cfg['max_entries_per_file']
                found = found[:cfg['max_entries_per_file']]
            entries += found
    return stats, entries


def resolve_dir(d, base):
    p = Path(os.path.expanduser(d))
    return p if p.is_absolute() else Path(base) / p


def load_history(path):
    try:
        d = common.read_json(path)
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def build(work, label, new_terms, dirs, cfg, old):
    queries = [q for q in (old or {}).get('queries', []) if isinstance(q, dict) and q.get('label') != label
               and q.get('label') in LABELS]
    queries.append({'label': label, 'utc': utc_now(), 'terms': new_terms})
    queries.sort(key=lambda q: LABELS.index(q['label']))
    roots = [(d, resolve_dir(d, work)) for d in dirs]
    stats, entries = scan(roots, [(q['label'], q['terms']) for q in queries], cfg)
    order = {d: i for i, d in enumerate(dirs)}
    entries.sort(key=lambda e: (order[e['root']], e['file'], e['line']))
    ids = {}
    for e in (old or {}).get('entries', []):
        if isinstance(e, dict) and isinstance(e.get('id'), str):
            ids[(e.get('root'), e.get('file'), e.get('line'))] = e['id']
    nxt = 1 + max([int(i[1:]) for i in ids.values() if re.fullmatch(r'E[0-9]+', i)] or [0])
    for e in entries:
        k = (e['root'], e['file'], e['line'])
        if k in ids:
            e['id'] = ids[k]
        else:
            e['id'] = 'E%d' % nxt
            ids[k] = e['id']
            nxt += 1
    entries = [dict([('id', e['id'])] + [(k, v) for k, v in e.items() if k != 'id']) for e in entries]
    limits = {k: cfg[k] for k in ('max_files', 'max_file_bytes', 'max_total_bytes', 'max_entries_per_file',
                                  'max_excerpt_chars', 'window_lines', 'file_verdict_lines')}
    return {'stage': 'history', 'generated_utc': utc_now(), 'project_dirs': list(dirs), 'limits': limits, 'scan': stats,
            'queries': queries, 'entries': entries, 'note': NOTE}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd')
    sp = sub.add_parser('scan', help='search the project archives for the terms and write history.json')
    sp.add_argument('dir')
    sp.add_argument('--label', required=True, choices=LABELS)
    sp.add_argument('--terms-file')
    sp.add_argument('--term', action='append', default=[])
    sp.add_argument('--group', choices=GROUPS)
    sp.add_argument('--for', dest='for_id')
    sp.add_argument('--project-dir', action='append', default=[])
    a = ap.parse_args(argv)
    if a.cmd != 'scan':
        ap.print_usage(sys.stderr)
        return 2
    work = Path(a.dir)
    if not work.is_dir():
        print('history.py: %s is not a directory' % work, file=sys.stderr)
        return 2
    try:
        raw = []
        if a.terms_file:
            data = common.read_json(a.terms_file)
            raw += data.get('terms') if isinstance(data, dict) else data if isinstance(data, list) else [None]
        raw += [parse_cli_term(s, a.label, a.group, a.for_id) for s in a.term]
        terms = normalise_terms(raw, a.label)
    except (OSError, ValueError, TypeError) as e:
        print('history.py: usage error: %s' % e, file=sys.stderr)
        return 2
    dirs = [str(d) for d in a.project_dir]
    if not dirs:
        try:
            intake = common.read_json(work / 'intake.json')
            dirs = [d for d in (intake.get('project_dirs') or []) if isinstance(d, str) and d.strip()]
        except (OSError, ValueError, AttributeError):
            dirs = []
    if not dirs:
        print('history.py: no project folder: pass --project-dir or write project_dirs in intake.json', file=sys.stderr)
        return 2
    for d in dirs:
        if not resolve_dir(d, work if not a.project_dir else Path.cwd()).is_dir():
            print('history.py: project folder %s cannot be read (not a directory)' % d, file=sys.stderr)
            return 1
    cfg = common.config()['history']
    base = Path.cwd() if a.project_dir else work
    old = load_history(work / HISTORY)
    result = build(base, a.label, terms, dirs, cfg, old)
    common.write_json(work / HISTORY, result)
    ent = result['entries']
    print(json.dumps({'history': str((work / HISTORY).resolve()), 'files_scanned': result['scan']['files_scanned'],
                      'entries': len(ent), 'classed': sum(1 for e in ent if e['verdict'] == 'classed'),
                      'tried': sum(1 for e in ent if e['verdict'] == 'tried'), 'truncated': result['scan']['truncated']},
                     indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
