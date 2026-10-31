#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Mechanical check of the code references of a code-plugin run (plugins/code.md; audit of 2026-10-31, section 6 item 4). No model.
Reads REPORT.md, card.json and mechanisms.json of DIR (or the files given with --file), finds every code reference and checks it:
  repository   the repository named exists (GitHub, engine github-repo: code_sources.GitHubRepo)
  commit       the SHA (abbreviated or full) is a commit OF THAT repository (/commits on it; whether it is in the default
               branch history, /compare), full SHA reported
  file         the file exists at the commit (local git directory first, by `git show` only, verifier/code_files.py; else the raw host)
  lines        each cited line or range lies within the file
  snippets     each quoted fragment attached to a reference is present, whitespace-normalised, within the cited lines widened by k lines
               (config.json code_refs.snippet_window_lines; fragments shorter than code_refs.snippet_min_chars are ignored)
  licence      SPDX licence detected by GitHub at the commit (NOASSERTION: read the file named in `path`)
Reference forms read: `repo:<owner>/<name>/<path>[:line[-end]]@<SHA>`; `<path>[:line[-end][,line[-end]...]]@<SHA>` (repository from the permalink of the
same bibliography entry or JSON string, else --repo, else capsule.json Y.repo, else the only repository of the permalinks);
`local:<path>[:line[-end]]@<SHA>` (host code X: local git directories only, verifier/code_files.py run_repos and --x-repo);
GitHub permalinks `<web>/<owner>/<name>/blob/<SHA>/<path>#L<a>[-L<b>]` with the anchors that follow (` ; #L<c>`); `l.<a>[-<b>]` after a
reference in the same text adds a range; `<owner>/<name>@<SHA>` (a known repository) checks the commit only.
Lines written in prose (banc code 2026-10-31, defect 5: 0/17 lines checked in C1): "line 12", "lines 206-207 and 271-302", "lines 57-106",
"L120", "L120-L135" belong to a reference when that is unambiguous: in a segment (bibliography line, JSON string) with exactly one reference,
every "line(s) ..." range; otherwise (and always for the L<n> form) only "lines A-B of|in <ref>" / "L12 in <ref>" (just before it) and
"<ref> (lines A-B)" / "<ref>, L12" (just after it). The others
are counted `prose_lines_unattached` (not guessed). Ranges from prose are marked on the reference (`ranges_from_prose`).
In REPORT.md a fragment ("...", “...”, «...», `...`) belongs to the sentence that carries it and is checked against the references of the
bibliography entries [n] that sentence cites (found in any of them = found); in a JSON file, against the references of the same string.
Status per reference: verified | failed (repository, commit or file absent, line out of bounds) | unchecked (no repository named, rate
limit, offline, no local X directory; a bare path whose commit is not in the default repository: ambiguous, not failed). A bare path also
cited `local:` with the same commit is host code X. A snippet not found is a warning (prose quotes may paraphrase). GitHub quota: anonymous requests
are paced by config.json code_intervals; a rate-limited answer stops the GitHub API calls (raw reads of full SHAs go on) and leaves the
rest unchecked. The token VP_GITHUB_TOKEN is used only if already resolvable by the key rule (KEYS.md), never printed.
Usage: check_code_refs.py DIR [--file PATH ...] [--repo OWNER/NAME] [--x-repo PATH ...] [--x-prefix SUBDIR ...] [--state DIR] [--offline] [--strict]
Output: JSON on stdout; exit code 0 = no failure (unchecked and snippet warnings allowed), 1 = at least one failure (with --strict also
an unchecked reference or a snippet not found), 2 = usage error.
Import: extract(path) -> [occurrence]; check(paths, run_dir=None, repo=None, x_repos=(), gh=None, x_prefixes=()) -> dict."""
import argparse, json, pathlib, re, sys
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE / 'verifier'))
import code_sources as sc   # noqa: E402  (GitHubRepo, CodeClient, config)
import code_files as cf     # noqa: E402  (local git directories, git show)

CFG = sc.CFG['code_refs']
K, MIN_CHARS = int(CFG['snippet_window_lines']), int(CFG['snippet_min_chars'])
DEFAULT_FILES = ('REPORT.md', 'card.json', 'mechanisms.json')
WEB = re.escape(sc.GH['web'])
REF = re.compile(r'(?<![\w/.@:-])(?P<kind>repo:|local:)?(?P<path>[A-Za-z0-9_.][\w.\-/]*?)(?::L?(?P<line>\d+)(?:\s?[-–]\s?L?(?P<end>\d+))?'
                 r'(?P<more>(?:,\s?L?\d+(?:\s?[-–]\s?L?\d+)?)*))?@(?P<sha>[0-9a-f]{7,40})(?![0-9A-Za-z])')   # path:a-b,c-d@SHA (several ranges)
LINK = re.compile(WEB + r'(?P<repo>' + sc.GH_REPO + r')/blob/(?P<sha>[0-9a-f]{7,40})/(?P<path>[^\s#)\]>,;`]+)(?:#L(?P<line>\d+)(?:-L(?P<end>\d+))?)?'
                  r'(?P<more>(?:\s*;\s*#L\d+(?:-L\d+)?)*)')
ANCHOR = re.compile(r'#L(\d+)(?:-L(\d+))?')
LRANGE = re.compile(r'\bl\.\s?(\d+)(?:\s?[-–]\s?(\d+))?')
QUOTES = (re.compile(r'"([^"\n]+)"'), re.compile(r'“([^”\n]+)”'), re.compile(r'«\s?([^»\n]+?)\s?»'), re.compile(r'`([^`\n]+)`'))
ENTRY = re.compile(r'^\s*\[(\d{1,3})\]')
CITE = re.compile(r'\[(\d{1,3})\]')
PROSE = re.compile(r'\blines?\s+(\d+(?:\s*[-–]\s*\d+)?(?:\s*(?:,|and|&)\s*\d+(?:\s*[-–]\s*\d+)?)*)', re.I)   # line 12, lines 3-5 and 9-11
PROSE_L = re.compile(r'(?<![\w#/:.-])L(\d+)(?:\s?[-–]\s?L?(\d+))?\b')                                       # L120, L120-L135 (not #L: permalinks)
PROSE_OF = re.compile(r'^\s+(?:of|in)\s+$', re.I)                                                         # "lines 3-5 of <ref>"
PROSE_AFTER = re.compile(r'^[\s,;:(\[]{0,3}$')                                                            # "<ref> (lines 3-5)", "<ref>, L12"
SENTENCE = re.compile(r'(?<=[.!?])\s+(?=[A-Z"“«(*\[])')


def _ranges(m, text_after=''):
    out = []
    if m.group('line'): out.append((int(m.group('line')), int(m.group('end') or m.group('line'))))
    if m.re is REF and m.group('more'):                                  # LINK's own 'more' (anchors) is read by _segment_refs
        out += [(int(a), int(b or a)) for a, b in re.findall(r'L?(\d+)(?:\s?[-–]\s?L?(\d+))?', m.group('more'))]
    for a, b in LRANGE.findall(text_after): out.append((int(a), int(b or a)))
    return out


def _prose_ranges(text, refspans):
    """Prose line ranges of a segment outside the reference spans: [(start, end, [(a, b)])]."""
    out = []
    for m in PROSE.finditer(text):
        if any(a <= m.start() < b for a, b in refspans): continue
        rg = [(int(a), int(b or a)) for a, b in re.findall(r'(\d+)(?:\s*[-–]\s*(\d+))?', m.group(1))]
        out.append((m.start(), m.end(), rg, False))
    for m in PROSE_L.finditer(text):                                     # L<n>: adjacent to a reference only ("L2 cache" is no line)
        if any(a <= m.start() < b for a, b in refspans): continue
        out.append((m.start(), m.end(), [(int(m.group(1)), int(m.group(2) or m.group(1)))], True))
    return out


def _attach_prose(text, occ, spans):
    """Adds the prose line ranges of the segment to its references when unambiguous (module docstring); -> number left unattached."""
    pr = _prose_ranges(text, [s for s in spans])
    left = 0
    for s, e, rg, adjacent_only in pr:
        if len(occ) == 1 and not adjacent_only: tgt = occ[0]
        else:
            tgt = next((o for o, (a, b) in zip(occ, spans) if a >= e and PROSE_OF.match(text[e:a])), None) \
                or next((o for o, (a, b) in zip(occ, spans) if b <= s and PROSE_AFTER.match(text[b:s])), None)
        if tgt is None: left += 1; continue
        new = [x for x in rg if x not in tgt['ranges']]
        tgt['ranges'] += new; tgt['prose_ranges'] = tgt.get('prose_ranges', []) + new
    return left


def _segment_refs(text, where):
    """References of one text segment (a JSON string, a bibliography entry, a line of prose): [occurrence]."""
    occ, spans = [], []
    for m in LINK.finditer(text):
        rg = _ranges(m) + [(int(a), int(b or a)) for a, b in ANCHOR.findall(m.group('more') or '')]
        occ.append({'side': 'Y', 'repo': m.group('repo'), 'path': m.group('path'), 'sha': m.group('sha'), 'ranges': rg, 'where': where, 'form': 'permalink'})
        spans.append(m.span())
    found = [m for m in REF.finditer(text) if not any(a <= m.start() < b for a, b in spans)]
    for i, m in enumerate(found):
        after = text[m.end(): found[i + 1].start() if i + 1 < len(found) else len(text)]
        kind, path = m.group('kind') or '', m.group('path')
        o = {'side': 'X' if kind == 'local:' else 'Y', 'repo': None, 'path': path, 'sha': m.group('sha'), 'ranges': _ranges(m, after), 'where': where,
             'form': kind.rstrip(':') or 'bare'}
        if kind == 'repo:':
            parts = path.split('/', 2)
            if len(parts) < 3: continue
            o.update(repo=parts[0] + '/' + parts[1], path=parts[2])
        occ.append(o); spans.append(m.span())
    if occ:
        order = sorted(range(len(occ)), key=lambda i: spans[i][0])
        occ_s, spans_s = [occ[i] for i in order], [spans[i] for i in order]
        left = _attach_prose(text, occ_s, spans_s)
        if left: occ_s[0]['prose_unattached'] = left
    return occ


def _fragments(text):
    out = []
    for rx in QUOTES:
        for m in rx.finditer(text):
            f = ' '.join(m.group(1).split())
            if len(f) >= MIN_CHARS and not REF.search(f) and not LINK.search(f): out.append(f)
    return out


def _strings(x, path=''):
    if isinstance(x, str): yield path, x
    elif isinstance(x, dict):
        for k, v in x.items(): yield from _strings(v, f'{path}.{k}' if path else str(k))
    elif isinstance(x, list):
        for i, v in enumerate(x): yield from _strings(v, f'{path}[{i}]')


def extract(path):
    """-> {'refs': [occurrence], 'snippets': [{'fragment', 'where', 'refs': [index in refs]}], 'context': {...}} for one file."""
    p = pathlib.Path(path); refs, snips = [], []
    if p.suffix.lower() == '.json':
        try: data = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, ValueError) as e: return {'refs': [], 'snippets': [], 'error': f'unreadable JSON: {type(e).__name__}'}
        hints = {}
        if isinstance(data, dict) and isinstance(data.get('sources'), dict):   # card.json: the url/repo field of a source names its repository
            for k, s in data['sources'].items():
                for f in ('url', 'repo', 'origin'):
                    r = sc.github_repo_of(str((s or {}).get(f) or '')) if isinstance(s, dict) else None
                    r = r or (re.sub(r'^(?:https://)?github\.com/', '', str((s or {}).get(f) or '')).removesuffix('.git') if isinstance(s, dict) else '')
                    if r and re.fullmatch(sc.GH_REPO, r): hints['sources.' + k] = r; break
        for where, s in _strings(data):
            occ = _segment_refs(s, f'{p.name}:{where}')
            for o in occ:
                h = next((v for k, v in hints.items() if where.startswith(k + '.')), None)
                if h and not o['repo']: o['repo'] = h
            linked = {o['repo'] for o in occ if o['repo']}
            for o in occ:
                if not o['repo'] and o['side'] == 'Y' and len(linked) == 1: o['repo'] = next(iter(linked))
            base = len(refs); refs += occ
            if occ:
                for f in _fragments(s): snips.append({'fragment': f, 'where': f'{p.name}:{where}', 'refs': list(range(base, base + len(occ)))})
        return {'refs': refs, 'snippets': snips}
    text = p.read_text(encoding='utf-8', errors='replace')
    entries = {}
    for n, line in enumerate(text.splitlines(), 1):
        m = ENTRY.match(line)
        occ = _segment_refs(line, f'{p.name}:{n}')
        linked = {o['repo'] for o in occ if o['repo']}
        for o in occ:
            if not o['repo'] and o['side'] == 'Y' and len(linked) == 1: o['repo'] = next(iter(linked))
        base = len(refs); refs += occ
        if m: entries.setdefault(int(m.group(1)), []).extend(range(base, base + len(occ)))
    for n, line in enumerate(text.splitlines(), 1):                      # prose: a quote checked against the entries its sentence cites
        if ENTRY.match(line) or line.lstrip().startswith('#'): continue
        for sent in SENTENCE.split(line):
            cited = [int(c) for c in CITE.findall(sent)]
            idx = sorted({i for c in cited for i in entries.get(c, [])})
            if not idx: continue
            for f in _fragments(sent): snips.append({'fragment': f, 'where': f'{p.name}:{n}', 'refs': idx, 'cites': sorted(set(cited))})
    return {'refs': refs, 'snippets': snips}


def _norm(s): return ' '.join(s.replace('“', '"').replace('”', '"').replace('’', "'").split())


class Checker:
    """Memoised checks over local git directories and GitHub (gh: code_sources.GitHubRepo or a test double with the same methods)."""
    def __init__(self, gh, repos, x_prefixes=()):
        self.gh, self.repos, self.files, self.commits, self.licences, self.infos = gh, repos, {}, {}, {}, {}
        self.x_prefixes = [''] + [p.strip('/') + '/' for p in x_prefixes if p.strip('/')]

    def _gh(self, fn, *a):
        if self.gh is None: return None, 'offline (no GitHub check)'
        try: return fn(*a), None
        except ValueError as e: return None, str(e)
        except RuntimeError as e: return None, str(e)

    def repository(self, repo):
        if repo not in self.infos: self.infos[repo] = self._gh(self.gh.info if self.gh else None, repo)
        return self.infos[repo]

    def commit(self, repo, sha):
        k = (repo, sha)
        if k not in self.commits: self.commits[k] = self._gh(self.gh.resolve if self.gh else None, repo, sha)
        return self.commits[k]

    def licence(self, repo, sha):
        k = (repo, sha)
        if k not in self.licences: self.licences[k] = self._gh(self.gh.licence if self.gh else None, repo, sha)
        return self.licences[k]

    def local(self, path, sha, x=False):
        """git show in the local directories; for X, the path is also tried under each --x-prefix (X = a subtree of its git directory)."""
        k = ('local', path, sha, x)
        if k not in self.files:
            t, rec = None, {'reason': 'no local git directory'}
            for pre in (self.x_prefixes if x else ['']):
                if not self.repos: break
                t, rec = cf.read_local({'path': pre + path, 'sha': sha}, self.repos)
                if t is not None or not rec.get('commit'): break
            self.files[k] = (t, rec)
        return self.files[k]

    def raw(self, repo, sha, path):
        k = (repo, sha, path)
        if k not in self.files: self.files[k] = self._gh(self.gh.file if self.gh else None, repo, sha, path)
        return self.files[k]


def _check_ref(r, ck):
    """Fills r['checks'] and r['status'] (and r['text'] kept apart for the snippets)."""
    c = r['checks'] = {}; fail = []; unchecked = []; text = None
    if r['side'] == 'X':
        t, rec = ck.local(r['path'], r['sha'], x=True)
        if rec.get('commit'):
            c['commit'] = {'status': 'ok', 'sha': rec['commit'], 'repo': rec.get('repo')}; r['sha_full'] = rec['commit']
            if t is None: c['file'] = {'status': 'absent', 'reason': rec.get('reason')}; fail.append('file')
            else: c['file'] = {'status': 'ok', 'method': 'git show'}; text = t
        else: c['commit'] = {'status': 'unchecked', 'reason': 'local (X) reference: ' + rec.get('reason', 'not found')}; unchecked.append('commit')
        c['licence'] = {'status': 'not checked (host code X)'}
    elif not r['repo']:
        c['repository'] = {'status': 'unchecked', 'reason': 'no repository named (repo:<owner>/<name>/<path>@<SHA>, a permalink, --repo or capsule.json Y.repo)'}
        unchecked.append('repository')
        t, rec = ck.local(r['path'], r['sha']) if r['kind'] == 'file' else (None, {})
        if t is not None: c['file'] = {'status': 'ok', 'method': 'git show (local mirror)', 'repo': rec.get('repo')}; text = t; r['sha_full'] = rec.get('commit')
    else:
        info, err = ck.repository(r['repo'])
        if info: c['repository'] = {'status': 'ok', 'default_branch': info.get('default_branch')}
        elif err in ('provider_error:HTTP404', 'repository'): c['repository'] = {'status': 'absent', 'reason': err}; fail.append('repository')
        else: c['repository'] = {'status': 'unchecked', 'reason': err}; unchecked.append('repository')
        com, err = ck.commit(r['repo'], r['sha']) if 'repository' not in fail else (None, 'repository absent')
        full = None
        if com:
            full = com['sha']; r['sha_full'] = full
            c['commit'] = {'status': 'ok', 'sha': full, 'date': com.get('date'), 'membership': com.get('membership'), 'in_default_branch': com.get('in_default_branch')}
        elif err in ('commit_not_in_repository', 'commit_mismatch', 'sha') and r.get('repo_from') == 'default':
            c['commit'] = {'status': 'unchecked', 'reason': f"{err} in the default repository {r['repo']}: the bare reference names no repository"}
            unchecked.append('commit'); err = 'repository absent'
        elif err in ('commit_not_in_repository', 'commit_mismatch', 'sha'): c['commit'] = {'status': 'absent', 'reason': err}; fail.append('commit')
        elif err != 'repository absent': c['commit'] = {'status': 'unchecked', 'reason': err}; unchecked.append('commit')
        if r['kind'] == 'file' and not fail and err != 'repository absent':
            t, rec = ck.local(r['path'], r['sha'])                        # a local mirror of Y answers first (git show)
            if t is not None: c['file'] = {'status': 'ok', 'method': 'git show (local mirror)'}; text = t; r['sha_full'] = r.get('sha_full') or rec.get('commit')
            else:
                sha40 = full or (r['sha'] if len(r['sha']) == 40 else None)
                if not sha40: c['file'] = {'status': 'unchecked', 'reason': 'abbreviated SHA not resolved'}; unchecked.append('file')
                else:
                    f, err = ck.raw(r['repo'], sha40, r['path'])
                    if f: c['file'] = {'status': 'ok', 'method': 'github raw at the SHA', 'permanent_url': f.get('permanent_url')}; text = f['text']
                    elif err in ('file_not_found', 'reference'): c['file'] = {'status': 'absent', 'reason': err}; fail.append('file')
                    else: c['file'] = {'status': 'unchecked', 'reason': err}; unchecked.append('file')
        if (not fail or fail == ['file']) and err != 'repository absent':
            lic, err = ck.licence(r['repo'], full or r['sha'])
            c['licence'] = {'status': 'ok', 'spdx': lic.get('spdx'), 'path': lic.get('path')} if lic else {'status': 'unchecked', 'reason': err}
    if text is not None and r['ranges']:
        n = len(cf.git_lines(text))
        bad = [list(x) for x in r['ranges'] if not 1 <= x[0] <= x[1] <= n]
        c['lines'] = {'status': 'out_of_bounds' if bad else 'in_bounds', 'lines_in_file': n, **({'out_of_bounds': bad} if bad else {})}
        if bad: fail.append('lines')
    elif r['ranges']: c['lines'] = {'status': 'unchecked'}
    r['status'] = 'failed' if fail else 'unchecked' if unchecked or (r['kind'] == 'file' and text is None) else 'verified'
    if fail: r['failed'] = fail
    return text


def _window(text, ranges):
    lines = cf.git_lines(text)
    if not ranges: return _norm(text)
    keep = set()
    for a, b in ranges:
        keep |= set(range(max(1, a - K), min(len(lines), b + K) + 1))
    return _norm(' '.join(lines[i - 1] for i in sorted(keep)))


def check(paths, run_dir=None, repo=None, x_repos=(), gh=None, x_prefixes=()):
    """Checks the references of the files `paths` -> report dict (see the module docstring)."""
    occ, snips, errors = [], [], []
    for p in paths:
        e = extract(p)
        if e.get('error'): errors.append({'file': str(p), 'error': e['error']})
        base = len(occ); occ += e['refs']
        snips += [dict(s, refs=[base + i for i in s['refs']]) for s in e['snippets']]
    known = {o['repo'] for o in occ if o['repo']}
    x_side = {(o['path'], o['sha'][:7]) for o in occ if o['side'] == 'X'}
    for o in occ:                                                        # a bare path also cited local: with the same commit is host code X
        if o['form'] == 'bare' and (o['path'], o['sha'][:7]) in x_side: o['side'] = 'X'
    default = repo
    if not default and run_dir:
        y = cf._json(pathlib.Path(run_dir) / 'capsule.json').get('Y')
        v = str((y or {}).get('repo') or '') if isinstance(y, dict) else ''
        v = re.sub(r'^(?:https://)?github\.com/', '', v).removesuffix('.git')
        if re.fullmatch(sc.GH_REPO, v): default = v
    if not default and len(known) == 1: default = next(iter(known))
    if default: known.add(default)
    refs, index = [], {}
    for i, o in enumerate(occ):
        kind = 'commit' if o['side'] == 'Y' and o['form'] == 'bare' and o['path'] in known else 'file'
        rp = o['path'] if kind == 'commit' else (o['repo'] or (default if o['side'] == 'Y' else None))
        key = (o['side'], rp, '' if kind == 'commit' else o['path'], o['sha'][:7])
        if key not in index:
            index[key] = len(refs)
            refs.append({'id': None, 'side': o['side'], 'kind': kind, 'repo': rp, 'path': None if kind == 'commit' else o['path'], 'sha': o['sha'],
                         'ranges': [], 'occurrences': [], 'repo_from': 'named' if o['repo'] or kind == 'commit' else ('default' if rp else None)})
        r = refs[index[key]]
        if len(o['sha']) > len(r['sha']): r['sha'] = o['sha']
        r['ranges'] += [x for x in o['ranges'] if x not in r['ranges']]; r['occurrences'].append(o['where'])
        if o.get('prose_ranges'): r['ranges_from_prose'] = sorted(set(map(tuple, r.get('ranges_from_prose', []))) | set(o['prose_ranges']))
        o['ref'] = index[key]
    repos = cf.run_repos(run_dir, list(x_repos)) if run_dir or x_repos else []
    ck = Checker(gh, repos, x_prefixes); texts = {}
    quota = gh.rate() if gh is not None and hasattr(gh, 'rate') else None
    for j, r in enumerate(refs):
        r['id'] = ('local:' if r['side'] == 'X' else 'repo:' + r['repo'] + '/' if r['repo'] and r['kind'] == 'file' else '') + (r['path'] or r['repo'] or '') + '@' + r['sha']
        r['ranges'].sort()
        texts[j] = _check_ref(r, ck)
    out_snips = []
    for s in snips:
        targets = sorted({occ[i]['ref'] for i in s['refs']})
        st, found_in, elsewhere = 'unchecked', None, None
        frag = _norm(s['fragment'])
        for i in s['refs']:                                              # the lines cited by this occurrence, else by the reference
            j = occ[i]['ref']
            if texts.get(j) is None: continue
            if st == 'unchecked': st = 'not_found'
            if frag in _window(texts[j], occ[i]['ranges'] or refs[j]['ranges']): st, found_in = 'found', refs[j]['id']; break
            if frag in _norm(texts[j]): elsewhere = refs[j]['id']
        if st == 'not_found' and elsewhere: st, found_in = 'found_outside_cited_lines', elsewhere
        out_snips.append({'fragment': s['fragment'], 'where': s['where'], 'status': st, **({'found_in': found_in} if found_in else {}),
                          'refs': [refs[j]['id'] for j in targets]})
    count = lambda xs, k, v: sum(1 for x in xs if x.get(k) == v)
    summary = {'references': len(refs), 'verified': count(refs, 'status', 'verified'), 'failed': count(refs, 'status', 'failed'),
               'unchecked': count(refs, 'status', 'unchecked'), 'snippets': len(out_snips), 'snippets_found': count(out_snips, 'status', 'found'),
               'snippets_outside_cited_lines': count(out_snips, 'status', 'found_outside_cited_lines'),
               'snippets_not_found': count(out_snips, 'status', 'not_found'), 'snippets_unchecked': count(out_snips, 'status', 'unchecked'),
               'refs_with_lines': sum(1 for r in refs if r['ranges']), 'refs_with_prose_lines': sum(1 for r in refs if r.get('ranges_from_prose')),
               'prose_lines_unattached': sum(o.get('prose_unattached', 0) for o in occ)}
    licences = {}
    for r in refs:
        lic = (r['checks'].get('licence') or {})
        if r['repo'] and lic.get('status') == 'ok': licences.setdefault(r['repo'], {})[r.get('sha_full') or r['sha']] = {'spdx': lic.get('spdx'), 'path': lic.get('path')}
    return {'files': [str(p) for p in paths], 'default_repo': default, 'window_lines': K, 'snippet_min_chars': MIN_CHARS,
            **({'github_quota_at_start': quota} if quota else {}), **({'errors': errors} if errors else {}),
            'summary': summary, 'licences': licences, 'refs': refs, 'snippets': out_snips,
            **({'github': dict(gh.extra)} if gh is not None and getattr(gh, 'extra', None) else {})}


def exit_code(rep, strict=False):
    s = rep['summary']
    if s['failed'] or rep.get('errors'): return 1
    if strict and (s['unchecked'] or s['snippets_not_found'] or s['snippets_unchecked']): return 1
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dir', nargs='?', help='run directory (REPORT.md, card.json, mechanisms.json; capsule.json for Y.repo, local X directories)')
    ap.add_argument('--file', action='append', default=[], help='file to read instead of the default ones (repeatable; .json or Markdown)')
    ap.add_argument('--repo', default=None, help='default repository <owner>/<name> of bare references')
    ap.add_argument('--x-repo', action='append', default=[], help='local git directory of X or of a Y mirror (repeatable)')
    ap.add_argument('--x-prefix', action='append', default=[], help='path of X inside its git directory, tried after the path as written (repeatable)')
    ap.add_argument('--state', default=None, help='state directory of the HTTP client (receipts, cache; default: <dir>/state, else ./vp-state)')
    ap.add_argument('--offline', action='store_true', help='no network: local git directories only')
    ap.add_argument('--strict', action='store_true', help='exit 1 also on unchecked references and snippets not found')
    a = ap.parse_args(argv)
    if not a.dir and not a.file: ap.print_usage(sys.stderr); return 2
    d = pathlib.Path(a.dir) if a.dir else None
    if d is not None and not d.is_dir(): print(f'check_code_refs.py: not a directory: {a.dir!r}', file=sys.stderr); return 2
    if a.repo and not re.fullmatch(sc.GH_REPO, a.repo): print('check_code_refs.py: --repo expects <owner>/<name>', file=sys.stderr); return 2
    paths = [pathlib.Path(f) for f in a.file] or [d / f for f in DEFAULT_FILES if (d / f).is_file()]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing or not paths: print(f'check_code_refs.py: no file to read ({", ".join(missing) or "none of " + ", ".join(DEFAULT_FILES)})', file=sys.stderr); return 2
    gh = None
    if not a.offline:
        state = pathlib.Path(a.state) if a.state else (d / 'state' if d is not None else pathlib.Path('vp-state'))
        gh = sc.GitHubRepo(sc.CodeClient(cache_dir=state))
    rep = check(paths, run_dir=d, repo=a.repo, x_repos=a.x_repo, gh=gh, x_prefixes=a.x_prefix)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return exit_code(rep, a.strict)


if __name__ == '__main__':
    sys.exit(main())
