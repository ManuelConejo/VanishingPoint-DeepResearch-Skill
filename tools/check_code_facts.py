#!/usr/bin/env python3
"""Mechanical check of the REPOSITORY FACTS asserted by a code-plugin run (companion of check_code_refs.py, which checks the code references).
No model. A fact is one value asserted about a GitHub repository or a package version:
  licence       SPDX licence of a repository (GitHub licence detection at the commit pinned by the claim's source, else at the last
                commit of the default branch before T)
  archived      archived flag of a repository (GitHub repository record: a current value, see below)
  last_commit   date of the last commit of the default branch before T (GitHubRepo.head_gated: GET /commits?sha=<default branch>&until=<T>,
                then resolved and passed through the gateway barrier: default branch history, repository created before T, committer date,
                backdate checks; committer date, author date accepted). A pinned commit passes GitHubRepo.barrier too.
  pushed_at     repository-wide push date (current record; monotonic: a current value before T is the value at T)
  vulnerability OSV advisory <id> affects / does not affect <package> <version>; <id> is fixed in <version>; no known vulnerability for
                a 40-hex commit (OSV query by commit) -- advisories published on/after T are never used
Where the facts are read: card.json (each claims[].text, one sentence each; its source key gives the repository and the pinned commit when
the text names none) and mechanisms.json (the `licence` field of each mechanism); REPORT.md only with --prose (sentences that name exactly one
repository or one advisory: prose is less regular than the annex). A claim may carry several facts (`not archived, last commit <date>`).
Repository of a fact: the only one named in its clause (`<owner>/<name>` of a known repository, a GitHub URL, the name part of a known repository when
unique, `(Y)` = the default repository, `(X)` = --x-name), else the only repository named in the text, else the claim's source (card
sources[key].code `repo:<owner>/<name>[/<path>]@<SHA>`, a bare `<path>@<SHA>` = the default repository, `local:` = host code X; its url,
repo or origin field; a GitHub URL in its title). Known repositories: those of the card sources, --repo, capsule.json Y.repo, --x-name.
A licence named after a verb of reading ("GitHub reports NOASSERTION") is a reading of a record, not an assertion, when the text affirms another
licence (NOASSERTION: always). An `<owner>/<name>` unknown to the card sources is a target when it opens a sentence, follows `repository`/`of`/
`upstream`, or is followed by `repository` (target_from clause/text); a package name is never deduced into a repository.
Default repository: --repo, else capsule.json Y.repo, else the only repository of the card sources.
Status per fact: CONFIRMED | CONTRADICTED | UNCHECKABLE with a typed reason (`reason_type`):
  network        transport error, timeout, offline, 5xx, malformed answer
  rate_limited   provider quota exhausted (GitHub 403 + X-RateLimit-Remaining 0, 429)
  access_denied  401/403/451, bot challenge (never circumvented)
  not_found      the repository / advisory is unknown to the API (renamed, deleted, outside OSV): never read as a contradiction
  no_api         the API does not carry the value (licence NOASSERTION or not detected, no explicit version list, bound reached)
  after_T        the only observable value is after T (commit or advisory dated on/after T, record changed after T, claim of a post-T date)
  no_target      no repository / package identified for the fact
A failed access is never CONTRADICTED. Current values (archived, licence of the record, OSV records modified after T): when the check runs
within config.json code_facts.current_value_days days of T they stand for T; later, agreement is CONFIRMED (marked as_of now) and
disagreement UNCHECKABLE (after_T): the value may have changed after T. Date tolerance: code_facts.commit_date_tolerance_days.
Usage: check_code_facts.py DIR [--file PATH ...] [--T YYYY-MM-DD] [--repo OWNER/NAME] [--x-name OWNER/NAME] [--prose] [--state DIR]
       [--offline] [--strict] [--today YYYY-MM-DD]
T: --T, else run.json T, else the journal of the gateway state (state/journal.jsonl); none -> usage error.
Output: JSON on stdout; exit code 0 = no CONTRADICTED fact, 1 = at least one (with --strict also an UNCHECKABLE one), 2 = usage error.
Import: extract(paths, ...) -> {'facts', 'unparsed', ...}; check(paths, T, ..., gh=None, osv=None) -> report dict."""
import argparse, datetime, json, pathlib, re, sys
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import code_sources as sc   # noqa: E402  (GitHubRepo, Vulns, CodeClient, config)
from sources._common import Barrier   # noqa: E402  (the gateway's date barrier: GitHubRepo.barrier / head_gated take it)

CFG = sc.CFG['code_facts']
CURRENT_DAYS, DATE_TOL = int(CFG['current_value_days']), int(CFG['commit_date_tolerance_days'])
DEFAULT_FILES = ('card.json', 'mechanisms.json')
GH_URL = re.compile(re.escape(sc.GH['web']) + r'(' + sc.GH_REPO + r')(?=[/\s)\],;.]|$)')
REPO_TOKEN = re.compile(r'(?<![\w./:-])(?:repo:)?(' + sc.GH_REPO + r')(?=$|[\s)\],;:@]|\.(?:\s|$))')
SOURCE_CODE = re.compile(r'^(?P<kind>repo:|local:)?(?P<body>[^@\s]+)@(?P<sha>[0-9a-f]{7,40})$')
DATE = re.compile(r'(?<![\d-])(\d{4}-\d{2}-\d{2})(?![\d])')
T_MARK = re.compile(r'(?<!\w)T\s*[=(:]\s*$|(?i:window\s+(?:opening\s+)?$|(?:from|to|since|until|before|after|between)\s+$)')   # T itself, window bounds
SENTENCE = re.compile(r'(?<=[.!?])\s+(?=[A-Za-z"“«(*`\[])')                # prose: a sentence may start with <owner>/<name> in lower case
SUBJECT_BEFORE = re.compile(r'(?:^|[.!?;:]\s+|\b(?:repository|repo|upstream|fork)\s+|\blicen[cs]es?(?:\s+file)?\s+of\s+)$', re.I)    # <owner>/<name> opening a sentence, or named as the repository
SUBJECT_AFTER = re.compile(r'\s+(?:repository|repo)\b', re.I)
CLAUSE = re.compile(r';|,\s+(?=(?:whereas|while|but|and|so)\b)|\s+whereas\s+|\s+while\s+|,\s+(?=[XY]\s+is\b)')

# SPDX identifiers recognised in a claim (a vocabulary, not a threshold); a family without version (GPL, LGPL, BSD) matches any version.
LICENCES = [
    ('NOASSERTION', r'\bNOASSERTION\b'),
    ('AGPL-3.0', r'\bAGPL(?:-?v?3(?:\.0)?)?(?:-only|-or-later|\+)?\b|\bGNU\s+Affero\s+General\s+Public\s+Licen[cs]e\b|\bGNU\s+AGPL\b'),
    ('LGPL-2.1', r'\bLGPL-?v?2\.1\b|\bGNU\s+Lesser\s+General\s+Public\s+Licen[cs]e,?\s+v(?:ersion)?\s?2\.1\b'),
    ('LGPL-3.0', r'\bLGPL-?v?3(?:\.0)?\b|\bGNU\s+Lesser\s+General\s+Public\s+Licen[cs]e,?\s+v(?:ersion)?\s?3\b'),
    ('LGPL', r'\bLGPL\b|\bGNU\s+Lesser\s+General\s+Public\s+Licen[cs]e\b'),
    ('GPL-2.0', r'(?<![AL])\bGPL-?v?2(?:\.0)?\b|\bGNU\s+General\s+Public\s+Licen[cs]e,?\s+v(?:ersion)?\s?2\b'),
    ('GPL-3.0', r'(?<![AL])\bGPL-?v?3(?:\.0)?\b|\bGNU\s+General\s+Public\s+Licen[cs]e,?\s+v(?:ersion)?\s?3\b'),
    ('GPL', r'(?<![AL])\bGPL\b|\bGNU\s+General\s+Public\s+Licen[cs]e\b'),
    ('Apache-2.0', r'\bApache(?:[- ]Licen[cs]e)?,?(?:[- ]Version)?[- ]?2(?:\.0)?\b'),
    ('MIT', r'\bMIT\b'),
    ('BSD-3-Clause', r'\bBSD-3-Clause\b|\b3-[Cc]lause\s+BSD\b|\bBSD\s+3-[Cc]lause\b|\bNew\s+BSD\b|\bBSD-3\b(?!-)'),
    ('BSD-2-Clause', r'\bBSD-2-Clause\b|\b2-[Cc]lause\s+BSD\b|\bBSD\s+2-[Cc]lause\b|\bSimplified\s+BSD\b|\bBSD-2\b(?!-)'),
    ('0BSD', r'\b0BSD\b'),
    ('BSD', r'\bBSD\b'),
    ('MPL-2.0', r'\bMPL[- ]?2(?:\.0)?\b|\bMozilla\s+Public\s+Licen[cs]e,?\s+(?:v(?:ersion)?\s?)?2(?:\.0)?\b'),
    ('ISC', r'\bISC\b'), ('Unlicense', r'\bUnlicense\b'), ('CC0-1.0', r'\bCC0(?:-1\.0)?\b'), ('BSL-1.0', r'\bBSL-1\.0\b|\bBoost\s+Software\s+Licen[cs]e\b'),
    ('EPL-2.0', r'\bEPL-2\.0\b'), ('Zlib', r'\bZlib\b'),
    ('CC-BY-SA-4.0', r'\bCC-BY-SA-4\.0\b'), ('CC-BY-4.0', r'\bCC-BY-4\.0\b'), ('CC-BY-3.0', r'\bCC-BY-3\.0\b'), ('OFL-1.1', r'\bOFL-1\.1\b'),
    ('PolyForm-Noncommercial-1.0.0', r'\bPolyForm[- ]Non[- ]?commercial\b|\bPolyForm\s+NC\b'),
]
LICENCES = [(k, re.compile(v, re.I if k not in ('MIT', 'ISC', 'BSD') else 0)) for k, v in LICENCES]
# A licence named after a verb of reading ("GitHub reports NOASSERTION", "the API detects MIT") is a reading of a record, not what the text affirms.
OBSERVED = re.compile(r'\b(?:GitHub|API|detect(?:s|ed|ion)|report(?:s|ed)?|return(?:s|ed)|show(?:s|ed))\b[^.;()]{0,40}$', re.I)
CONNECTORS = re.compile(r'[\s,/()&+"\'`]*(?:(?:or|and|and/or|either|both|dual|dual-licen[cs]ed|licen[cs]ed?|licen[cs]es?|under|with|the|at\s+your\s+option|option|your)[\s,/()&+"\'`]*)*', re.I)
LIC_WORD = re.compile(r'licen[cs]|\bSPDX\b', re.I)
ARCHIVED = re.compile(r'(?:\b(?:is|was|are|remains)\s+|\(\s*|,\s*)(?P<neg>not\s+)?(?:flagged\s+(?:as\s+)?|marked\s+(?:as\s+)?)?archived\b(?!\s+(?:flag|status|date|on|at|since|between))', re.I)
ARCHIVED_BOOL = re.compile(r'\barchived\s*(?:[:=]|flag\s+(?:is\s+)?|is\s+)?\s*(?P<v>true|false)\b', re.I)
LAST_COMMIT = re.compile(r'\blast\s+(?:[\w-]+\s+){0,2}?commit\b', re.I)
PUSHED = re.compile(r'\bpushed[_ ]at\b|\blast\s+push\b', re.I)
ADVISORY = re.compile(r'\b(GHSA(?:-[23456789cfghjmpqrvwx]{4}){3}|CVE-\d{4}-\d{4,}|PYSEC-\d{4}-\d+|RUSTSEC-\d{4}-\d+|GO-\d{4}-\d+|OSV-\d{4}-\d+)\b')
PKG_VER = r'(?P<pkg>[A-Za-z][\w.-]*?)(?:\s*==\s*|\s+|@)v?(?P<ver>\d+(?:\.\d+)+(?:[-+]?[A-Za-z0-9]+)*)'
NOT_AFFECT = re.compile(r'\b(?:does\s+not|do\s+not|doesn\'t)\s+affect\s+' + PKG_VER + r'|' + PKG_VER.replace('pkg', 'pkg2').replace('ver', 'ver2')
                        + r'\s+(?:is|was)\s+not\s+affected\b', re.I)
AFFECT = re.compile(r'\baffects?\s+' + PKG_VER + r'|' + PKG_VER.replace('pkg', 'pkg2').replace('ver', 'ver2') + r'\s+(?:is|was)\s+affected\s+by\b', re.I)
VER = r'v?\d+(?:\.\d+)+[\w.+-]*?(?=[\s,;)\]]|\.?$|\.\s)'
FIXED = re.compile(r'\b(?:fixed|patched|resolved|addressed)\s+(?:in|from|by)\s+(?:(?P<pkg>[A-Za-z][\w.-]*)\s+)?(?:versions?\s+)?(?P<vers>' + VER
                   + r'(?:\s*(?:,|or|and)\s*' + VER + r')*)', re.I)
ECOSYSTEM = re.compile(r'\b(pypi|npm|crates\.io|cargo|maven|rubygems|nuget|packagist)\b', re.I)
NO_VULN = re.compile(r'\bno\s+(?:known\s+)?(?:vulnerabilit(?:y|ies)|advisor(?:y|ies))\b', re.I)
PROSE_SKIP = re.compile(r'bibliograph|referenc|methodolog|appendix', re.I)   # report sections that describe the process, not the facts
SHA40 = re.compile(r'(?<![0-9a-f])([0-9a-f]{40})(?![0-9a-f])')
MECH_REF = re.compile(r'((?:[\w.-]+/)*[\w.-]+):\d+(?:-\d+)?@([0-9a-f]{7,40})')     # y_side of a mechanism: <path>:<line>@<SHA>
OSV_SYSTEM = {v: k for k, v in sc.OSV_ECOSYSTEM.items()}


def _repo(v):
    v = re.sub(r'^(?:https?://)?github\.com/', '', str(v or '').strip()).rstrip('/')
    v = v[:-4] if v.endswith('.git') else v
    return v if re.fullmatch(sc.GH_REPO, v) and v.split('/')[1] not in ('.', '..') else None


def _source(s, default):
    """A card source -> {'side': 'Y'|'X', 'repo', 'sha'} (repo None when unknown)."""
    if not isinstance(s, dict): return {'side': 'Y', 'repo': None, 'sha': None}
    out = {'side': 'Y', 'repo': None, 'sha': None}
    m = SOURCE_CODE.match(str(s.get('code') or s.get('local') or '').strip())
    if m:
        out['sha'] = m.group('sha')
        if m.group('kind') == 'local:' or s.get('local'): out['side'] = 'X'
        elif m.group('kind') == 'repo:':
            parts = m.group('body').split('/')
            out['repo'] = _repo('/'.join(parts[:2])) if len(parts) >= 2 else None
            if len(parts) > 2: out['path'] = re.sub(r':\d+(?:-\d+)?$', '', '/'.join(parts[2:]))   # the file: a licence may depend on its directory
        else: out['repo'] = default; out['path'] = re.sub(r':\d+(?:-\d+)?$', '', m.group('body'))   # a bare <path>@<SHA>: the default repository
    for f in ('url', 'repo', 'origin'):
        r = sc.github_repo_of(str(s.get(f) or '')) or _repo(s.get(f)) if s.get(f) else None
        if r: out['repo'] = r; break
    if not out['repo'] and out['side'] == 'Y':
        g = GH_URL.search(str(s.get('title') or '')) or GH_URL.search(str(s.get('code') or ''))
        if g: out['repo'] = _repo(g.group(1))
    return out


class Targets:
    """Repositories a text may name: known <owner>/<name>, GitHub URLs, unique name parts, (Y) and (X) markers."""
    def __init__(self, known, default, x_name, default_sha=None):
        self.known, self.default, self.x_name, self.default_sha = set(known), default, x_name, default_sha
        names = {}
        for r in self.known: names.setdefault(r.split('/')[1].lower(), set()).add(r)
        self.alias = {k: next(iter(v)) for k, v in names.items() if len(v) == 1 and len(k) >= 3}

    def named(self, text, aliases=True, unknown=False, x_alias=True):
        """[(position, repo or 'X')] in order of appearance (repo 'X' = host code X without --x-name); aliases=False: only <owner>/<name>
        and GitHub URLs (prose)."""
        out = []
        for m in GH_URL.finditer(text): out.append((m.start(), _repo(m.group(1))))
        for m in REPO_TOKEN.finditer(text):
            r = _repo(m.group(1))
            if r in self.known: out.append((m.start(), r))
        for m in (REPO_TOKEN.finditer(text) if aliases and unknown else ()):   # an <owner>/<name> unknown to the sources but plainly the subject of the text
            r = _repo(m.group(1))
            if r and r not in self.known and not re.fullmatch(r'v\d+', r.split('/')[1]) and (SUBJECT_BEFORE.search(text[:m.start()])
                                                                                               or SUBJECT_AFTER.match(text[m.end():])):
                out.append((m.start(), r))
        for k, r in (self.alias.items() if aliases else ()):
            if not x_alias and r == self.x_name: continue                # licence field: X is the comparison, not the subject
            for m in re.finditer(r'(?<![\w/.-])' + re.escape(k) + r'(?![\w/-])', text, re.I):
                out.append((m.start(), r))
        for m in (re.finditer(r'\((X|Y)\)|(?<![\w/.-])(X|Y)\s+is\b', text) if aliases else ()):
            side = m.group(1) or m.group(2)
            r = self.default if side == 'Y' else (self.x_name or 'X')
            if r: out.append((m.start(), r))
        seen, res = set(), []
        for p, r in sorted(out):
            if r and (p, r) not in seen: seen.add((p, r)); res.append((p, r))
        return res


def _clauses(text):
    """[(start, end)] of the clauses of a sentence (split at ; and before whereas / while / but / and / so, and before 'X is' / 'Y is')."""
    out, start = [], 0
    for m in CLAUSE.finditer(text):
        out.append((start, m.start())); start = m.end()
    out.append((start, len(text)))
    return out


POSSESSIVE_START = re.compile(r'\s*(?:its|their|it|this|that|these|those)\b', re.I)      # "...; its last commit is": refers to a subject, not to the repository named before
FOREIGN_REPO = re.compile(r'\b(?:repository|repo)\s+`?(' + sc.GH_REPO + r')`?|\(\s*(?:repository|repo)\s+(' + sc.GH_REPO + r')\s*\)', re.I)


def _target(pos, text, named, fallback, clause_only=False):
    """Repository of a fact at `pos`: the one named in its clause, else the only one named in the text, else the fallback (source)."""
    for a, b in _clauses(text):
        if a <= pos <= b:
            inside = {r for p, r in named if a <= p < b}
            if len(inside) == 1: return next(iter(inside)), 'clause'
            if len(inside) > 1: return None, 'ambiguous'                 # never guessed: a wrong attribution could yield a false CONTRADICTED
            known_here = {r for _, r in named}
            for m in FOREIGN_REPO.finditer(text[a:b]):                   # the clause names ANOTHER repository (unknown to the sources): not ours
                if _repo(m.group(1) or m.group(2)) not in known_here: return None, 'ambiguous'
    every = {r for _, r in named}
    if clause_only and every: return None, 'ambiguous'               # several licences in the text: a repository named in another clause is not this one's
    if len(every) == 1:
        a, b = next(((a, b) for a, b in _clauses(text) if a <= pos <= b), (0, len(text)))
        if POSSESSIVE_START.match(text[a:b]): return None, 'ambiguous'      # "...; its last commit is": the subject is not the repository named in another clause
        return next(iter(every)), 'text'
    if len(every) > 1: return None, 'ambiguous'
    return fallback, 'source' if fallback else None


def _dates_after(text, start):
    for m in DATE.finditer(text, start):
        if T_MARK.search(text[max(0, m.start() - 30):m.start()]): continue
        yield m


def _facts_of(text, where, tg, src, kind='claim'):
    """Facts asserted in one text (a claim, a licence field, a prose sentence): [{type, claimed, repo|package, ...}], [unparsed note]."""
    named = tg.named(text, aliases=kind != 'prose', unknown=kind == 'claim', x_alias=kind != 'licence_field')
    fb = src.get('repo') if src.get('side') == 'Y' else (tg.x_name or 'X')
    facts, unparsed = [], []
    multi_licence = False

    def add(pos, typ, claimed, **kw):
        repo, how = _target(pos, text, named, fb, clause_only=typ == 'licence' and multi_licence)
        if how == 'ambiguous' or repo is None:
            if kind == 'licence_field' or how == 'ambiguous':
                unparsed.append({'where': where, 'type': typ, 'claimed': claimed, 'why': 'no single repository for this clause', 'text': text[:300]})
                return
        mine = how == 'source' or (repo and repo == src.get('repo')) or (src.get('side') == 'X' and repo == (tg.x_name or 'X'))
        sha = src.get('sha') if mine else (tg.default_sha if repo and repo == tg.default else None)
        facts.append(dict({'type': typ, 'claimed': claimed, 'repo': repo, 'sha': sha, 'target_from': how, 'where': where, 'text': text[:300]},
                          **({'path': src['path']} if mine and src.get('path') else {}), **kw))

    if LIC_WORD.search(text) or kind == 'licence_field':
        per_clause = []
        for a, b in _clauses(text):
            seg, hits = text[a:b], []
            for k, rx in LICENCES:
                for m in rx.finditer(seg):
                    if not any(s <= m.start() < e for s, e, _ in hits): hits.append((m.start(), m.end(), k))
            per_clause.append((a, b, seg, hits))
        affirmed = {k for _, _, seg, hits in per_clause for s_, _, k in hits if not OBSERVED.search(seg[:s_])}
        multi_licence = len(affirmed) > 1
        for a, b, seg, hits in per_clause:
            hits = [h for h in hits if not (OBSERVED.search(seg[:h[0]]) and (h[2] == 'NOASSERTION' or affirmed))]   # a reading beside an affirmation: not a fact
            ids = sorted({k for _, _, k in hits})
            if len(ids) == 1:
                if re.search(r'\b(?:no|not|never|any)\s+(?:\S+\s+){0,2}?' + re.escape(seg[hits[0][0]:hits[0][1]]), seg, re.I) and ids != ['NOASSERTION']:
                    continue                                              # "no AGPL text may be copied", "any AGPL text": not an assertion
                add(a + hits[0][0], 'licence', ids[0])
            elif len(ids) > 1:
                order = [k for _, _, k in sorted(hits)]
                order = [k for i, k in enumerate(order) if k not in order[:i]]
                srt = sorted(hits)
                if any(not CONNECTORS.fullmatch(seg[srt[i][1]:srt[i + 1][0]]) for i in range(len(srt) - 1)):   # other words between: several subjects, not one expression
                    unparsed.append({'where': where, 'type': 'licence', 'claimed': ids, 'why': 'several licences in one clause', 'text': text[:300]}); continue
                between = seg[min(h[1] for h in hits):max(h[0] for h in hits)]
                op = ' OR ' if re.search(r'\bor\b|\bdual\b|/|\beither\b', between + ' ' + seg, re.I) and not re.search(r'\band\b', between, re.I) \
                    else ' AND ' if re.search(r'\band\b', between, re.I) and re.search(r'\bboth\b|\bAND\b', seg) else None
                if op: add(a + min(h[0] for h in hits), 'licence', op.join(order))   # an SPDX expression: dual (OR) or cumulative (AND) licence
                else: unparsed.append({'where': where, 'type': 'licence', 'claimed': ids, 'why': 'several licences in one clause', 'text': text[:300]})
    for m in ARCHIVED.finditer(text):
        if kind == 'prose' and not re.match(r'\s*(?:is|was|are|remains)\b', m.group(0), re.I): continue   # prose: "<repo> is (not) archived" only
        add(m.start(), 'archived', not m.group('neg'))
    for m in ARCHIVED_BOOL.finditer(text):
        if not any(f['type'] == 'archived' for f in facts): add(m.start(), 'archived', m.group('v').lower() == 'true')
    for m in LAST_COMMIT.finditer(text):
        clause_end = next((b for a, b in _clauses(text) if a <= m.start() <= b), len(text))
        d = next((x for x in _dates_after(text, m.end()) if x.start() < clause_end), None)
        if d: add(m.start(), 'last_commit', d.group(1))
    for m in PUSHED.finditer(text):
        clause_end = next((b for a, b in _clauses(text) if a <= m.start() <= b), len(text))
        d = next((x for x in _dates_after(text, m.end()) if x.start() < clause_end), None)
        if d: add(m.start(), 'pushed_at', d.group(1))
    def advisories(pos):
        """Advisory identifiers of the ;-clause of `pos` (else of the whole text): one advisory and its aliases expected."""
        a = text.rfind(';', 0, pos) + 1; b = text.find(';', pos); b = len(text) if b < 0 else b
        return list(dict.fromkeys(ADVISORY.findall(text[a:b]))) or list(dict.fromkeys(ADVISORY.findall(text)))
    if ADVISORY.search(text):
        for rx, typ in ((NOT_AFFECT, 'not_affected'), (AFFECT, 'affected')):
            for m in rx.finditer(text):
                if typ == 'affected' and NOT_AFFECT.search(text[max(0, m.start() - 12):m.end()]): continue
                pkg, ver = m.group('pkg') or m.group('pkg2'), m.group('ver') or m.group('ver2')
                facts.append({'type': 'vulnerability', 'claimed': typ, 'advisory': advisories(m.start()), 'package': pkg, 'version': ver, 'where': where, 'text': text[:300]})
        for m in FIXED.finditer(text):
            pkgs = re.findall(r'\bfor\s+([A-Za-z][\w.-]*)', text[:m.start()])
            pkg = m.group('pkg') if m.group('pkg') and m.group('pkg').lower() not in ('version', 'versions') else (pkgs[-1] if pkgs else None)
            for v in re.findall(VER, m.group('vers')):
                facts.append({'type': 'vulnerability', 'claimed': 'fixed_in', 'advisory': advisories(m.start()), 'package': pkg, 'version': v.lstrip('v'),
                              'where': where, 'text': text[:300]})
    if NO_VULN.search(text):
        c = SHA40.search(text) or (re.match(r'[0-9a-f]{40}$', src.get('sha') or '') and src.get('sha'))
        c = c.group(1) if hasattr(c, 'group') else c
        pv = re.search(PKG_VER, text[NO_VULN.search(text).end():])
        if c: facts.append({'type': 'vulnerability', 'claimed': 'none_for_commit', 'commit': c, 'repo': fb, 'where': where, 'text': text[:300]})
        elif pv:
            eco = ECOSYSTEM.search(text)
            facts.append({'type': 'vulnerability', 'claimed': 'none_for_version', 'package': pv.group('pkg'), 'version': pv.group('ver'),
                          'ecosystem': {'crates.io': 'cargo'}.get(eco.group(1).lower(), eco.group(1).lower()) if eco else None, 'where': where, 'text': text[:300]})
    return facts, unparsed


def _json(p):
    try: return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError): return None


def extract(paths, run_dir=None, repo=None, x_name=None, prose=False):
    """Facts of the files `paths` (card.json, mechanisms.json, and REPORT.md with prose=True) -> {'facts', 'unparsed', 'default_repo', 'known'}."""
    docs = {pathlib.Path(p).name: (pathlib.Path(p), _json(p) if str(p).endswith('.json') else None) for p in paths}
    default, default_sha = repo, None
    y = (_json(pathlib.Path(run_dir) / 'capsule.json') or {}).get('Y') if run_dir else None
    if isinstance(y, dict) and _repo(y.get('repo')) and (not default or default == _repo(y.get('repo'))):
        default = _repo(y.get('repo'))                                   # capsule Y: repository and its pinned commit
        default_sha = y.get('sha') if re.fullmatch(r'[0-9a-f]{7,40}', str(y.get('sha') or '')) else None
    card = next((d for n, (p, d) in docs.items() if isinstance(d, dict) and isinstance(d.get('claims'), list)), None)
    sources = (card or {}).get('sources') if isinstance((card or {}).get('sources'), dict) else {}
    pre = {k: _source(s, None) for k, s in sources.items()}
    known = {s['repo'] for s in pre.values() if s['repo']}
    if not default and len(known) == 1: default = next(iter(known))
    if prose:                                                            # repositories of the report's bibliography (repo: ids, GitHub URLs)
        for n, (p, d) in docs.items():
            if d is None:
                t = p.read_text(encoding='utf-8', errors='replace')
                known |= {r for r in (_repo(x) for x in re.findall(r'(?<![\w/.-])repo:(' + sc.GH_REPO + r')(?=[/@])', t) + GH_URL.findall(t)) if r}
    known |= {r for r in (default, x_name) if r}
    tg = Targets(known, default, x_name, default_sha)
    srcs = {k: _source(s, default) for k, s in sources.items()}
    facts, unparsed = [], []
    for name, (p, d) in docs.items():
        if isinstance(d, dict) and isinstance(d.get('claims'), list):
            for c in d['claims']:
                if not isinstance(c, dict) or not isinstance(c.get('text'), str): continue
                key = (c.get('source') or {}).get('key') if isinstance(c.get('source'), dict) else None
                f, u = _facts_of(c['text'], f"{name}:claims.{c.get('id')}", tg, srcs.get(key, {'side': 'Y', 'repo': None, 'sha': None}))
                facts += f; unparsed += u
        elif isinstance(d, list):                                         # mechanisms.json
            for i, m in enumerate(d):
                if isinstance(m, dict) and isinstance(m.get('licence'), str):
                    ys = MECH_REF.search(str(m.get('y_side') or ''))             # the Y file of the mechanism: a licence may depend on its directory
                    src = {'side': 'Y', 'repo': default, 'sha': ys.group(2), 'path': ys.group(1)} if ys and default else {'side': 'Y', 'repo': None, 'sha': None}
                    f, u = _facts_of(m['licence'], f'{name}:[{i}].licence', tg, src, kind='licence_field')
                    facts += f; unparsed += u
        elif d is None and prose:
            text, skip = p.read_text(encoding='utf-8', errors='replace'), False
            for n, line in enumerate(text.splitlines(), 1):
                if re.match(r'^\s*#', line): skip = bool(PROSE_SKIP.search(line)); continue
                if skip or re.match(r'^\s*(?:\[\d+\]|\d+\.\s)', line): continue
                for sent in SENTENCE.split(line):
                    named = {r for _, r in tg.named(sent, aliases=False)}
                    if len(named) > 1 or (not named and not ADVISORY.search(sent)): continue
                    f, _ = _facts_of(sent, f'{name}:{n}', tg, {'side': 'Y', 'repo': None, 'sha': None}, kind='prose')
                    facts += [x for x in f if x.get('repo') or x['type'] == 'vulnerability']
    return {'facts': facts, 'unparsed': unparsed, 'default_repo': default, 'known': sorted(known)}


def _reason(err):
    """A provider error code (code_sources) -> reason_type."""
    e = str(err or '')
    if e == 'rate_limited': return 'rate_limited'
    if e in ('bot_challenge', 'credential_host') or re.fullmatch(r'provider_error:HTTP(401|403|407|451)', e): return 'access_denied'
    if e in ('provider_error:HTTP404', 'provider_error:HTTP410', 'commit_not_in_repository', 'repository'): return 'not_found'
    return 'network'


def _day(s):
    try: return datetime.date.fromisoformat(str(s or '')[:10])
    except ValueError: return None


class Observer:
    """Memoised API reads (gh: code_sources.GitHubRepo or a test double; osv: code_sources.Vulns or a test double); errors kept typed.
    Commits are dated by the same barrier as the gateway (Codex review 2026-10-31, item 2): GitHubRepo.head_gated without a SHA,
    GitHubRepo.barrier for a resolved commit (gate, committer date, backdate checks); no weaker dating path of its own."""
    def __init__(self, gh, osv, T):
        self.gh, self.osv, self.T, self.memo = gh, osv, T, {}
        self.B = Barrier(T)

    def _get(self, key, fn, *a):
        if key not in self.memo:
            if fn is None: self.memo[key] = (None, 'offline')
            else:
                try: self.memo[key] = (fn(*a), None)
                except (ValueError, RuntimeError) as e: self.memo[key] = (None, str(e))
        return self.memo[key]

    def info(self, repo): return self._get(('info', repo), self.gh and self.gh.info, repo)
    def licence(self, repo, sha): return self._get(('lic', repo, sha), self.gh and self.gh.licence, repo, sha)
    def licence_read(self, repo, sha, detected): return self._get(('lread', repo, sha), self.gh and getattr(self.gh, 'licence_read', None), repo, sha, detected)
    def resolve(self, repo, sha): return self._get(('res', repo, sha), self.gh and self.gh.resolve, repo, sha)
    def head(self, repo): return self._get(('head', repo), self.gh and self.gh.head_gated, repo, self.B)
    def barrier(self, repo, r): return self._get(('bar', repo, r.get('sha')), self.gh and self.gh.barrier, repo, r, self.B)
    def file(self, repo, sha, path): return self._get(('file', repo, sha, path), self.gh and getattr(self.gh, 'file', None), repo, sha, path)
    def advisory(self, ident): return self._get(('adv', ident), self.osv and self.osv.get, ident)
    def query(self, system, pkg, ver): return self._get(('q', system, pkg, ver), self.osv and self.osv.query, system, pkg, ver)
    def by_commit(self, sha): return self._get(('c', sha), self.osv and self.osv.query_commit, sha)

    def commit_before_T(self, repo, sha=None):
        """The pinned commit (resolved, then GitHubRepo.barrier) or the last commit of the default branch before T (GitHubRepo.head_gated)
        -> (commit, None) | (None, (reason_type, why)); a refusal of the barrier is after_T, no candidate listed is no_api."""
        if sha:
            r, err = self.resolve(repo, sha)
            if err: return None, (_reason(err), err)
            why, err = self.barrier(repo, r)
            if err: return None, (_reason(err), err)
        else:
            res, err = self.head(repo)
            if err: return None, (_reason(err), err)
            r, why = res
        if why: return None, ('after_T' if why.startswith('after T') or 'on/after T' in why else 'no_api', why)
        d = _day(r.get('date'))
        if d is None or d >= self.T: return None, ('after_T', 'commit dated on/after T (or undated)')
        return r, None


def _unc(f, rtype, why, **kw): f.update(status='UNCHECKABLE', reason_type=rtype, reason=why, **kw); return f


def _current(f, agree, observed, fresh, what):
    """A current value (as of now): stands for T within code_facts.current_value_days; later, agreement only confirms."""
    f['observed'], f['as_of'] = observed, 'now'
    if agree: f['status'] = 'CONFIRMED'; return f
    if fresh: f['status'] = 'CONTRADICTED'; return f
    return _unc(f, 'after_T', f'{what} is a current value observed more than {CURRENT_DAYS} days after T (code_facts.current_value_days): it may have changed after T')


def _lic_one(claimed, observed):
    o = re.sub(r'-(?:only|or-later)$', '', str(observed or ''))
    return claimed == o or (claimed in ('GPL', 'LGPL', 'BSD') and o.startswith(claimed + '-')) or (claimed == 'BSD' and o == '0BSD')


def _lic_match(claimed, observed):
    """A claimed licence against an observed SPDX expression: a single licence matches a single one or a member of an OR (dual licence: either
    may be chosen); a claimed expression matches the same kind with the same members; a single licence never matches an AND (both apply)."""
    kc, ic = sc.spdx_members(claimed); ko, io = sc.spdx_members(observed)
    if kc == 'single': return ko in ('single', 'or') and any(_lic_one(ic[0] if ic else claimed, o) for o in io)
    return kc == ko and len(ic) == len(io) and all(any(_lic_one(c, o) for o in io) for c in ic)


def _check_repo_fact(f, ob, T, fresh):
    repo = f.get('repo')
    if not repo or repo == 'X': return _unc(f, 'no_target', 'host code X without --x-name' if repo == 'X' else 'no repository named for this fact')
    info, err = ob.info(repo)
    if err: return _unc(f, _reason(err), err)
    created = _day(info.get('created_at'))
    if created is None or created >= T: return _unc(f, 'after_T', 'repository created on/after T (or undated)')
    if f['type'] == 'archived':
        return _current(f, info.get('archived') is f['claimed'], info.get('archived'), fresh, 'the archived flag')
    if f['type'] == 'pushed_at':
        p, c = _day(info.get('pushed_at')), _day(f['claimed'])
        if p is None: return _unc(f, 'no_api', 'no pushed_at in the repository record')
        f['observed'] = info.get('pushed_at')
        if p >= T: return _unc(f, 'after_T', 'pushed after T: the value at T is not observable')
        f['status'] = 'CONFIRMED' if abs((p - c).days) <= DATE_TOL else 'CONTRADICTED'; f['basis'] = 'pushed_at before T = value at T (monotonic)'
        return f
    if f['type'] == 'last_commit':
        c = _day(f['claimed'])
        if c >= T: return _unc(f, 'after_T', 'claimed date on/after T: a post-T fact', leak=True)
        r, why = ob.commit_before_T(repo)
        if why: return _unc(f, *why)
        days = [x for x in (_day(r.get('date')), _day(r.get('author_date'))) if x]
        f.update(observed=r.get('date'), observed_author_date=r.get('author_date'), commit=r.get('sha'), basis='last commit of the default branch before T',
                 **({'backdate_check': r['backdate_check'].get('verdict')} if isinstance(r.get('backdate_check'), dict) else {}))
        f['status'] = 'CONFIRMED' if any(abs((x - c).days) <= DATE_TOL for x in days) else 'CONTRADICTED'
        return f
    # licence
    sha = f.get('sha')
    r, why = ob.commit_before_T(repo, sha)
    if why: return _unc(f, *why)
    lic, err = ob.licence(repo, r['sha'])
    if err: return _unc(f, _reason(err), err)
    obs = lic.get('spdx')
    f.update(observed=obs, licence_path=lic.get('path'), commit=r['sha'], basis='GitHub licence detection at ' + ('the pinned commit' if sha else 'the last commit of the default branch before T'),
             **({'backdate_check': r['backdate_check'].get('verdict')} if isinstance(r.get('backdate_check'), dict) else {}))
    if f['claimed'] == 'NOASSERTION':
        if obs is None: return _unc(f, 'no_api', 'no licence file detected by GitHub at the commit')
        f['status'] = 'CONFIRMED' if obs == 'NOASSERTION' else 'CONTRADICTED'; return f
    lr, _ = ob.licence_read(repo, r['sha'], obs)                           # the files read at the SHA (manifest, root files, per directory)
    lr = lr if isinstance(lr, dict) and lr.get('status') == 'read' else None
    seen = [obs] if obs not in (None, 'NOASSERTION', 'NONE') else []
    dirs = [d for d in (lr or {}).get('by_directory') or [] if d.get('identified') and not d.get('same_as_root')]   # a directory with ITS OWN licence
    under = {}                                                             # cited file -> the innermost directory with its own licence
    for p in f.get('paths') or []:
        ds = [d for d in dirs if (p + '/').startswith(d['directory'] + '/')]
        if ds: under[p] = max(ds, key=lambda x: len(x['directory']))
    if lr:
        f['licence_read'] = {k: lr.get(k) for k in ('expression', 'basis')}
        if lr.get('expression') and lr['expression'] not in seen: seen.append(lr['expression'])
        if dirs and not under: f['licence_by_directory'] = [{'directory': d['directory'], 'identified': d.get('identified')} for d in dirs]
    cited = []                                                             # the cited file IS a manifest: its own licence field decides
    L = sc.GH['licence_read']
    for p in f.get('paths') or []:
        if p.rsplit('/', 1)[-1] in L['manifests'] or p.endswith(tuple(L['manifest_suffixes'])):
            t, _ = ob.file(repo, r['sha'], p)
            e = sc.spdx_expression(sc.manifest_licence(p, t['text'])) if isinstance(t, dict) and t.get('text') else None
            if e: cited.append((p, e))
    if cited:
        f['observed_expressions'] = [e for _, e in cited]; f['basis'] = 'licence field of the cited manifest at the commit'
        f['licence_read'] = {'manifests': [{'path': p, 'expression': e} for p, e in cited]}
        f['status'] = 'CONFIRMED' if all(_lic_match(f['claimed'], e) for _, e in cited) else 'CONTRADICTED'
        return f
    if under:                                                              # a cited file lies under a directory with its own licence
        bad, open_ = [], []
        for p, d in under.items():
            hit = [i for i in d['identified'] if _lic_match(f['claimed'], i)] or ([1] if _lic_match(f['claimed'], ' OR '.join(d['identified'])) else [])
            row = {'path': p, 'directory': d['directory'], 'licence_files': d.get('paths'), 'identified': d['identified']}
            if not hit and not _lic_match(f['claimed'], ' AND '.join(d['identified'])): bad.append(row)
            elif len(d['identified']) > 1 and sc.spdx_members(f['claimed'])[0] == 'single': open_.append(row)   # several licences there: OR or AND not decided
        rest = [p for p in f.get('paths') or [] if p not in under]
        f['licence_read']['directories'] = [{'path': p, 'directory': d['directory'], 'identified': d['identified']} for p, d in under.items()]
        f['basis'] = 'licence files of the directory of the cited file at the commit' + (' (other cited files: the root licence)' if rest else '')
        if bad: f.update(status='CONTRADICTED', contradicted_for=bad); return f
        if open_: return _unc(f, 'no_api', 'several licence files in the directory of the cited file: whether they apply together (AND) or as a choice (OR) is to be read', undecided_for=open_)
        if not rest: f['status'] = 'CONFIRMED'; return f
    if not seen:
        return _unc(f, 'no_api', f"GitHub does not identify the licence at the commit ({obs or 'no licence file detected'}) and no licence file nor manifest "
                                 f"field read at the SHA identifies it; the file {lic.get('path') or ''} is to be read")
    f['observed_expressions'] = seen
    f['status'] = 'CONFIRMED' if any(_lic_match(f['claimed'], o) for o in seen) else 'CONTRADICTED'
    if f['status'] == 'CONFIRMED' and not _lic_match(f['claimed'], seen[0]): f['basis'] += '; confirmed by the files read at the SHA (' + ((lr or {}).get('basis') or '') + ')'
    return f


def _osv_ids(v): return {v.get('id')} | set(v.get('aliases') or [])


def _check_vuln(f, ob, T, fresh):
    kind = f['claimed']
    if kind == 'none_for_commit':
        vs, err = ob.by_commit(f['commit'])
        if err: return _unc(f, _reason(err), err)
        known = [v for v in vs if _day(v.get('published')) and _day(v.get('published')) < T]
        f['observed'] = sorted(v.get('id') for v in known)
        if not known: f['status'] = 'CONFIRMED'; return f
        if any(_day(v.get('modified')) and _day(v.get('modified')) < T for v in known) or fresh: f['status'] = 'CONTRADICTED'; return f
        return _unc(f, 'after_T', 'the advisories listed for the commit were modified on/after T: their ranges at T are not observable')
    if kind == 'none_for_version':
        if not f.get('ecosystem'): return _unc(f, 'no_target', 'no ecosystem named for the package (pypi:, npm, ...)')
        vs, err = ob.query(f['ecosystem'], f['package'], f['version'])
        if err: return _unc(f, _reason(err), err)
        known = [v for v in vs if _day(v.get('published')) and _day(v.get('published')) < T]
        f['observed'] = sorted(v.get('id') for v in known)
        if not known: f['status'] = 'CONFIRMED'; return f
        if any(_day(v.get('modified')) and _day(v.get('modified')) < T for v in known) or fresh: f['status'] = 'CONTRADICTED'; return f
        return _unc(f, 'after_T', 'the advisories listed for the version were modified on/after T: their ranges at T are not observable')
    ids = f.get('advisory') or []
    adv, err, used = None, None, None
    for i in ids:                                                        # the first identifier OSV knows (aliases are equivalent)
        adv, err = ob.advisory(i)
        if adv: used = i; break
        if _reason(err) != 'not_found': break
    if not adv: return _unc(f, _reason(err), err)
    f['osv'] = adv.get('id')
    if set(ids) - _osv_ids(adv): return _unc(f, 'no_target', 'several advisories named for one fact: ' + ', '.join(sorted(set(ids) - _osv_ids(adv))) + ' not an alias of ' + used)
    pub, mod = _day(adv.get('published')), _day(adv.get('modified'))
    if pub is None or pub >= T: return _unc(f, 'after_T', 'advisory published on/after T (or undated): not known at T', leak=pub is not None)
    edited = not (mod and mod < T)
    affected = [a for a in adv.get('affected') or [] if isinstance(a, dict)]
    pkg = (f.get('package') or '').lower().replace('_', '-')
    mine = [a for a in affected if str((a.get('package') or {}).get('name') or '').lower().replace('_', '-') == pkg] if pkg else affected
    if not mine: return _unc(f, 'no_target' if pkg else 'no_api', f'package {pkg or "?"} not in the affected list of {used}')
    if kind == 'fixed_in':
        fixed = sorted({str(e.get('fixed')) for a in mine for r in a.get('ranges') or [] if r.get('type') != 'GIT' for e in r.get('events') or []
                        if isinstance(e, dict) and e.get('fixed')})   # version ranges (GIT ranges hold commits)
        if not fixed: return _unc(f, 'no_api', 'no fixed version in the advisory ranges')
        f['observed'] = fixed
        if f['version'] in fixed: f['status'] = 'CONFIRMED'; return f
        if edited and not fresh: return _unc(f, 'after_T', 'advisory modified on/after T: the fixed versions at T are not observable')
        f['status'] = 'CONTRADICTED'; return f
    eco = str((mine[0].get('package') or {}).get('ecosystem') or '')
    system = OSV_SYSTEM.get(eco)
    if not system: return _unc(f, 'no_api', f'ecosystem {eco or "?"} not queried by the osv engine')
    vs, err = ob.query(system, (mine[0].get('package') or {}).get('name'), f['version'])
    if err: return _unc(f, _reason(err), err)
    hit = any(set(ids) & _osv_ids(v) or adv.get('id') in _osv_ids(v) for v in vs)
    f['observed'] = 'affected' if hit else 'not_affected'
    if (kind == 'affected') == hit: f['status'] = 'CONFIRMED'; return f
    if edited and not fresh: return _unc(f, 'after_T', 'advisory modified on/after T: its ranges at T are not observable')
    f['status'] = 'CONTRADICTED'
    return f


def _merge(facts):
    """One fact per (type, target, claimed value, pinned commit); the places that assert it are listed."""
    out, index = [], {}
    key = lambda f, sha: json.dumps([f['type'], f.get('repo'), f.get('claimed'), sha, f.get('package'), f.get('version'), f.get('commit'), sorted(f.get('advisory') or [])])
    for f in facts:
        k = key(f, f.get('sha'))
        if not f.get('sha'):                                              # unpinned: the same fact pinned by another place of the run
            k = next((key(f, g.get('sha')) for g in out if key(f, g.get('sha')) in index), k)
        if k not in index:
            index[k] = len(out); out.append(dict({x: v for x, v in f.items() if x != 'path'}, where=[f['where']], **({'paths': [f['path']]} if f.get('path') else {})))
        else:
            g = out[index[k]]
            if f['where'] not in g['where']: g['where'].append(f['where'])
            if f.get('path') and f['path'] not in g.setdefault('paths', []): g['paths'].append(f['path'])   # a licence may depend on the directory
    return out


def check(paths, T, run_dir=None, repo=None, x_name=None, gh=None, osv=None, prose=False, today=None):
    """Checks the facts of `paths` at T (datetime.date) -> report dict (module docstring)."""
    e = extract(paths, run_dir, repo, x_name, prose)
    today = today or datetime.date.today()
    fresh = (today - T).days <= CURRENT_DAYS
    ob = Observer(gh, osv, T)
    facts = _merge(e['facts'])
    for f in facts:
        if f['type'] == 'vulnerability': _check_vuln(f, ob, T, fresh)
        else: _check_repo_fact(f, ob, T, fresh)
    count = lambda v: sum(1 for f in facts if f.get('status') == v)
    reasons = {}
    for f in facts:
        if f.get('status') == 'UNCHECKABLE': reasons[f['reason_type']] = reasons.get(f['reason_type'], 0) + 1
    by_type = {}
    for f in facts:
        t = by_type.setdefault(f['type'], {'CONFIRMED': 0, 'CONTRADICTED': 0, 'UNCHECKABLE': 0}); t[f['status']] += 1
    return {'files': [str(p) for p in paths], 'T': T.isoformat(), 'checked_on': today.isoformat(), 'current_values_stand_for_T': fresh,
            'default_repo': e['default_repo'], 'known_repos': e['known'],
            'summary': {'facts': len(facts), 'confirmed': count('CONFIRMED'), 'contradicted': count('CONTRADICTED'), 'uncheckable': count('UNCHECKABLE'),
                        'uncheckable_reasons': reasons, 'by_type': by_type, 'unparsed': len(e['unparsed'])},
            'facts': facts, 'unparsed': e['unparsed'],
            **({'github': dict(gh.extra)} if gh is not None and getattr(gh, 'extra', None) else {})}


def exit_code(rep, strict=False):
    s = rep['summary']
    if s['contradicted']: return 1
    return 1 if strict and s['uncheckable'] else 0


def run_T(d):
    """T of a run directory: run.json T (one value), else the first T of state/journal.jsonl; None when absent or ambiguous."""
    r = _json(d / 'run.json') or {}
    t = r.get('T')
    if isinstance(t, list): t = t[0] if len(set(t)) == 1 else None
    if not t:
        try:
            with open(d / 'state' / 'journal.jsonl', encoding='utf-8') as fh:
                for line in fh:
                    try: t = json.loads(line).get('T')
                    except ValueError: continue
                    if t: break
        except OSError: t = None
    return _day(t)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dir', nargs='?', help='run directory (card.json, mechanisms.json; capsule.json for Y.repo; run.json or state/journal.jsonl for T)')
    ap.add_argument('--file', action='append', default=[], help='file to read instead of the default ones (repeatable)')
    ap.add_argument('--T', default=None, help='date T of the run (YYYY-MM-DD; default: run.json, else the gateway journal)')
    ap.add_argument('--repo', default=None, help='default repository <owner>/<name> (Y) of bare references and of "(Y)"')
    ap.add_argument('--x-name', default=None, help='GitHub repository <owner>/<name> of the host code X ("(X)", local: sources)')
    ap.add_argument('--prose', action='store_true', help='also read REPORT.md (sentences naming exactly one repository or an advisory)')
    ap.add_argument('--state', default=None, help='state directory of the HTTP client (receipts, cache; default: <dir>/state-facts, else ./vp-state)')
    ap.add_argument('--offline', action='store_true', help='no network: every fact UNCHECKABLE (network)')
    ap.add_argument('--strict', action='store_true', help='exit 1 also when a fact is UNCHECKABLE')
    ap.add_argument('--today', default=None, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if not a.dir and not a.file: ap.print_usage(sys.stderr); return 2
    d = pathlib.Path(a.dir) if a.dir else None
    if d is not None and not d.is_dir(): print(f'check_code_facts.py: not a directory: {a.dir!r}', file=sys.stderr); return 2
    for o, v in (('--repo', a.repo), ('--x-name', a.x_name)):
        if v and not _repo(v): print(f'check_code_facts.py: {o} expects <owner>/<name>', file=sys.stderr); return 2
    T = _day(a.T) if a.T else (run_T(d) if d is not None else None)
    if T is None: print('check_code_facts.py: no date T (--T YYYY-MM-DD, run.json or state/journal.jsonl)', file=sys.stderr); return 2
    names = DEFAULT_FILES + (('REPORT.md',) if a.prose else ())
    paths = [pathlib.Path(f) for f in a.file] or [d / f for f in names if (d / f).is_file()]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing or not paths: print(f'check_code_facts.py: no file to read ({", ".join(missing) or "none of " + ", ".join(names)})', file=sys.stderr); return 2
    gh = osv = None
    if not a.offline:
        state = pathlib.Path(a.state) if a.state else (d / 'state-facts' if d is not None else pathlib.Path('vp-state'))
        client = sc.CodeClient(cache_dir=state)
        gh, osv = sc.GitHubRepo(client), sc.Vulns(client)
    rep = check(paths, T, run_dir=d, repo=_repo(a.repo) if a.repo else None, x_name=_repo(a.x_name) if a.x_name else None, gh=gh, osv=osv,
                prose=a.prose, today=_day(a.today) if a.today else None)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return exit_code(rep, a.strict)


if __name__ == '__main__':
    sys.exit(main())
