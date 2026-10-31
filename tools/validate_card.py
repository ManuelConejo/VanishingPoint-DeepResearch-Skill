#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Mechanical check of a question's working directory before delivery (SKILL.md, sections 6 to 8). No network, no model, standard library.
Usage: validate_card.py DIR [--header] [--prior-art]      --header: derives run.json from state/journal.jsonl (never written by hand)
--prior-art (optional "Prior art?" mode, SKILL.md; never by default): checks 1-5 and 9 and 13, plus the prior-art checks PA1-PA4 of
tools/prior_art.py (prior_art.json, element claims, PRIOR-ART.md current and consistent with the verified claims, a NOT FOUND with a recorded
search) in place of the report checks 6, 7, 8, 10, 11, 12 (no REPORT.md nor result.json in that mode).
Checks: 1 card.json (minimal schema); 2 source keys (an identifier field of a known kind, validate_card.IDS: doi, pmid, arxiv, celex, ecli... as declared by tools/sources/, or `code` for a file read at a SHA); 3 placeholders;
4 searches/ (>= 3, with queries); 5 verdicts.json handled (no ABSENT/INVALID left, known statuses); 6 REPORT.md: exactly the eight level-2
sections of the output contract, in order (Executive Summary 200-400 words, Introduction, Main Analysis with 4 to 8 findings headed
`### Finding n — <title>`, Synthesis & Insights, Limitations & Caveats, Recommendations, Bibliography, Methodology Appendix; or the same
eight titles and finding word in one other language of tools/report_lang.py, e.g. Résumé ... Annexe méthodologique, `### Constat n — <title>`;
a follow-up run, marked by followup.json, uses the bounds of config.json `followup` for the summary, the findings and the searches); 7 unverified claims
flagged; 8 result.json valid (validate_result); 9 run.json consistent with the journal; 10 "Source coverage" block present (in the methodology
appendix), with its active and skipped lines; 11 each [n] of the text is in the bibliography and each [n] entry is cited; 12 prose >= 80 % (bullet lines <= 20 %);
14 no cross-source statement on a single citation: a clause that compares, ranks, counts, excludes or reports a search outcome across sources
("the largest series [5]", "excluded [12]", "no later ruling was found [13]") and cites one source only, or only versions of one study
(preprint and article, registry record and report: tools/study_family.py, config.json `study_family`) (tools/cross_source.py; config.json
`cross_source`): the fact of the source in its own sentence with its [n], the comparison as the writer's synthesis without [n], or every
source compared cited;
13 (command line, runs with a gateway journal only) end steps done on the current files: state/finish_run.json, written by tools/finish_run.py,
whose fingerprints of REPORT.md, card.json, result.json and verdicts.json match the files (else: run finish_run.py, which runs these checks,
the retraction check, law_checks and the exports).
Output: problems (empty = OK), exit code 1 if there are any; then warnings (prefix `warning:`), never blocking: a code reference (field `code`
of card.json, ids of result.json) without a repository (`<path>@<SHA>` instead of `repo:<owner>/<name>/<path>@<40-hex SHA>`) or with a SHA
shorter than 40 hex (validate_result.code_warnings). Import: problems(dir) -> [str] (checks 1-12 and 14); warnings(dir) -> [str];
end_problems(dir) -> [str] (check 13); header(dir) -> dict."""
import hashlib, json, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from validate_result import problems as pb_result, warnings as warn_result, code_warnings
import sources as _reg   # noqa: E402  (source registry)
import report_lang as RL   # noqa: E402  (titles of the eight sections, one version per language)
import cross_source as CS   # noqa: E402  (check 14)
import study_family as SF   # noqa: E402  (check 14: versions of one study count as one source)

IDS = tuple(i['field'] for i in _reg.IDS if i['card'])   # card identifier fields, from the source declarations (tools/sources/): code = `<path>@<SHA>` or `local:<path>@<SHA>`; the others: ids served by the gateway engines (SKILL.md section 0 "Identity of sources")
MISFILED = re.compile(r'([a-z][a-z0-9]*):\S+')   # check 2: a gateway identifier (doi:, celex:, localdoc:...) written in the `code` field
STATUSES = {'FOUND', 'DISTORTED', 'ABSENT', 'SOURCE-UNAVAILABLE', 'INVALID', 'UNVERIFIED'}
UNHANDLED = {'ABSENT', 'INVALID'}
PLACEHOLDER = re.compile(r'TODO|TBD|FIXME|to be completed|lorem ipsum|XXX|<[a-z ]{3,30}>|\[\.\.\.\]|\?\?\?', re.I)
EDIT_MARKER = re.compile(r'(?<![A-Za-z0-9])[A-Z0-9_]*PLACEHOLDER[A-Z0-9_]*')   # check 3: an editing marker left by a two-step edit (e.g. a line `PLACEHOLDER_X` left in verdicts.json), case-sensitive
MARKED_FILES = ('REPORT.md', 'card.json', 'result.json', 'verdicts.json')
COVERAGE = RL.any_words('coverage'); ACTIVE = RL.any_words('active'); SKIPPED = RL.any_words('skipped'); UNVERIFIED = RL.any_words('unverified')
SECTIONS = RL.EN                     # canonical (English) titles; the report may use the eight titles of any one language of tools/report_lang.py
SUMMARY_WORDS = (200, 400); FINDINGS = (4, 8); BULLETS_MAX = 0.20
FOLLOWUP = (json.loads((pathlib.Path(__file__).resolve().parent / 'config.json').read_text(encoding='utf-8')).get('followup') or {})


def finding_heading(lang):
    """`### <word of the language> n — <title>`: the em dash (U+2014) is required by the contract."""
    return re.compile(r'^### ' + re.escape(RL.LANGS[lang]['finding']) + r' (\d+) — \S', re.M)


def is_followup(folder):
    """A follow-up run (SKILL.md "Follow-up in the conversation"): written by tools/followup.py, marker followup.json."""
    return (pathlib.Path(folder) / 'followup.json').is_file()
CITATION = re.compile(r'\[(\d{1,3})\]')


def sections(t):
    """Splits REPORT.md by level-2 headings: [(title, body)] in file order; a known title of any language of tools/report_lang.py is
    returned as its canonical English title (the raw titles: report_lang.raw_sections)."""
    return RL.sections(t)


def report_problems(t, followup=False, families=None):
    """Checks 6, 10, 11, 12, 14 on the text of REPORT.md (output contract, SKILL.md section 5). The eight titles are those of one language of
    tools/report_lang.py (all eight in the same language). followup=True: the bounds of a follow-up report (config.json `followup`).
    families = {n: family} of tools/study_family.py (check 14 counts studies, not documents); None: each [n] is its own study."""
    pb = []; raw = RL.raw_sections(t); lang = RL.title_language([s for s, _ in raw]); expected = RL.LANGS[lang]['sections']
    titles = [s for s, _ in raw]
    words = tuple(FOLLOWUP.get('summary_words') or SUMMARY_WORDS) if followup else SUMMARY_WORDS
    nf = tuple(FOLLOWUP.get('findings') or FINDINGS) if followup else FINDINGS
    if titles != expected:
        missing = [s for s in expected if s not in titles]; extra = [s for s in titles if s not in expected]
        pb.append(f'6 REPORT.md: eight level-2 sections expected in order ({RL.LANGS[lang]["name"]}) ' + ' > '.join(expected)
                  + (f'; missing: {missing}' if missing else '') + (f'; extra: {extra}' if extra else '') + ('; different order' if not missing and not extra else '')
                  + f' (all eight titles in one language of tools/report_lang.py: {", ".join(RL.LANGS)})')
    secs = sections(t); body = dict(secs)
    if 'Executive Summary' in body:
        n = len(body['Executive Summary'].split())
        if not words[0] <= n <= words[1]: pb.append(f'6 REPORT.md: Executive Summary of {n} words, {words[0]} to {words[1]} expected')
    if 'Main Analysis' in body:
        heads = re.findall(r'^### .*$', body['Main Analysis'], re.M); n = len(heads)
        if not nf[0] <= n <= nf[1]: pb.append(f'6 REPORT.md: Main Analysis has {n} level-3 finding(s), {nf[0]} to {nf[1]} expected')
        rx = finding_heading(lang); bad = [h for h in heads if not rx.match(h)]
        if bad: pb.append(f'6 REPORT.md: finding heading not in the form "### {RL.LANGS[lang]["finding"]} n — <title>": {bad[0]!r}')
    # 10 source coverage: present (methodology appendix), with its two lines
    m = COVERAGE.search(t)
    if not m: pb.append('10 REPORT.md: "Source coverage" block missing (active / skipped: reason + link; check_keys.py)')
    else:
        block = t[m.end():]; end = re.search(r'\n#{1,6} ', block); block = block[:end.start()] if end else block
        if not ACTIVE.search(block): pb.append('10 REPORT.md: "Source coverage" without an "active" line')
        if not SKIPPED.search(block): pb.append('10 REPORT.md: "Source coverage" without a "skipped" line (write "skipped: none" if applicable)')
    # 11 citations [n] <-> bibliography
    biblio = body.get('Bibliography', '')
    defined = {int(x) for x in re.findall(r'^\s*\[(\d{1,3})\]', biblio, re.M)}
    cited = {int(x) for s, c in secs if s != 'Bibliography' for x in CITATION.findall(c)}
    if not defined: pb.append('11 REPORT.md: bibliography without any [n] entry')
    if cited - defined: pb.append(f'11 REPORT.md: citations without a bibliography entry: {sorted(cited - defined)}')
    if defined - cited: pb.append(f'11 REPORT.md: bibliography entries never cited: {sorted(defined - cited)}')
    # 12 prose: bullet lines <= 20 % of text lines (headings and bibliography excluded)
    lines = [l for s, c in secs if s != 'Bibliography' for l in c.splitlines() if l.strip() and not l.startswith('#')]
    bullets = [l for l in lines if re.match(r'^\s*([-*+]|\d+[.)])\s', l)]
    if lines and len(bullets) / len(lines) > BULLETS_MAX: pb.append(f'12 REPORT.md: {len(bullets)} bullet lines out of {len(lines)} ({100*len(bullets)/len(lines):.0f} %), prose >= 80 % expected')
    # 14 cross-source statements carrying a single citation
    pb += CS.problems(t, lang, families)
    return pb


def load(p):
    try: return json.loads(p.read_text(encoding='utf-8'))
    except Exception as e: return e


def header(folder):
    """Header derived from the gateway journal: run, T, calls per command and engine, errors, identifiers seen."""
    j = pathlib.Path(folder) / 'state' / 'journal.jsonl'
    lines = [json.loads(l) for l in j.read_text(encoding='utf-8').splitlines() if l.strip()] if j.exists() else []
    e = {'source': 'state/journal.jsonl' if lines else 'no journal', 'run': sorted({l.get('run') for l in lines if l.get('run')}),
         'T': sorted({l.get('T') for l in lines if l.get('T')}), 'calls': len(lines), 'calls_per_command': {}, 'errors': 0, 'ids_seen': 0}
    seen = set()
    for l in lines:
        e['calls_per_command'][l.get('call')] = e['calls_per_command'].get(l.get('call'), 0) + 1
        e['errors'] += bool(l.get('error')); seen |= {i for i in (l.get('ids') or []) if i}
    e['ids_seen'] = len(seen)
    pools = {}
    for l in lines: pools[l.get('pool') or 'search'] = pools.get(l.get('pool') or 'search', 0) + 1
    if set(pools) - {'search'}: e['calls_per_pool'] = pools               # the verifier's own budget (gateway pool 'verifier')
    return e


FINISH_INPUTS = ('REPORT.md', 'card.json', 'result.json', 'verdicts.json', 'prior_art.json', 'PRIOR-ART.md')   # what the end steps read; a change after them makes them stale (the last two: prior-art mode only, absent otherwise)


def fingerprints(folder):
    """sha256 of each end-step input (None when absent), as written by tools/finish_run.py in state/finish_run.json."""
    d = pathlib.Path(folder)
    return {f: (hashlib.sha256((d / f).read_bytes()).hexdigest() if (d / f).is_file() else None) for f in FINISH_INPUTS}


def end_problems(folder):
    """Check 13: with a gateway journal (script mode), the end steps of tools/finish_run.py ran on the current files."""
    d = pathlib.Path(folder)
    if not (d / 'state' / 'journal.jsonl').exists(): return []          # injected mode: no script, no end-step receipt
    cmd = f'python3 -I tools/finish_run.py {folder} --T <T> --plugin plugins/<d>.md (it runs these checks, the retraction check, law_checks and the exports)'
    r = load(d / 'state' / 'finish_run.json') if (d / 'state' / 'finish_run.json').exists() else None
    if not isinstance(r, dict) or not isinstance(r.get('inputs'), dict): return [f'13 end steps not run (state/finish_run.json missing): run {cmd}']
    now = fingerprints(d)
    changed = [f for f in FINISH_INPUTS if r['inputs'].get(f) != now[f]]
    return [f'13 end steps stale: {", ".join(changed)} changed since the last finish_run.py: run {cmd}'] if changed else []


def warnings(folder):
    """Non-blocking deviations: code references of card.json (sources table and claims' own source) and code ids of result.json."""
    d = pathlib.Path(folder); out = []
    f = load(d / 'card.json') if (d / 'card.json').exists() else None
    if isinstance(f, dict):
        for k, s in sorted((f.get('sources') or {}).items()) if isinstance(f.get('sources'), dict) else []:
            for fld in ('code', 'local'):
                v = (s or {}).get(fld) if isinstance(s, dict) else None
                if v: out += [f'card.json source {k}.{fld}: {w}' for w in code_warnings(v if fld == 'code' or str(v).startswith('local:') else 'local:' + str(v))]
        for a in f.get('claims') or []:
            s = a.get('source') if isinstance(a, dict) else None
            if isinstance(s, dict) and not s.get('key') and s.get('code'):
                out += [f'card.json claim {a.get("id")}.source.code: {w}' for w in code_warnings(s['code'])]
    r = load(d / 'result.json') if (d / 'result.json').exists() else None
    if isinstance(r, dict): out += ['result.json ' + w for w in warn_result(r)]
    return out


def problems(folder, prior_art=False):
    """Checks 1-12; prior_art=True: checks 1-5 and 9 plus PA1-PA4 (tools/prior_art.py) in place of the report and result.json checks."""
    d = pathlib.Path(folder); pb = []
    # 1-2-3 card.json
    f = load(d / 'card.json') if (d / 'card.json').exists() else None
    keys_cited = set(); ids = set()
    if not isinstance(f, dict): pb.append('1 card.json: missing or unreadable JSON')
    else:
        for c in ('card_id', 'question', 'claims'):
            if c not in f: pb.append(f'1 card.json: missing field {c}')
        for i, a in enumerate(f.get('claims') or []):
            for c in ('id', 'text', 'source', 'location'):
                if not a.get(c) and a.get(c) != '': pb.append(f'1 claim {i}: missing field {c}')
            if a.get('id') in ids: pb.append(f'1 claim {a.get("id")}: duplicate id')
            ids.add(a.get('id'))
            if not str(a.get('text', '')).strip(): pb.append(f'1 claim {a.get("id")}: empty text')
            s = a.get('source') or {}
            if s.get('key'): keys_cited.add(s['key'])
            elif not any(s.get(k) for k in IDS): pb.append(f'2 claim {a.get("id")}: source without key nor identifier')
        table = f.get('sources') or {}
        for c in sorted(keys_cited):
            if c not in table: pb.append(f'2 source key cited but missing from card.sources: {c}')
            elif not any((table[c] or {}).get(k) for k in IDS): pb.append(f'2 source {c}: no identifier among {"/".join(IDS)}')
            elif (m := MISFILED.fullmatch(str((table[c] or {}).get('code') or '').strip())) and m.group(1) in IDS and m.group(1) not in ('code', 'local'):
                pb.append(f'2 source {c}: field code holds a {m.group(1)} identifier, not <path>@<SHA>: write {{"{m.group(1)}": "<identifier without the {m.group(1)}: prefix>"}}')
        for m in PLACEHOLDER.finditer(json.dumps(f, ensure_ascii=False)):
            pb.append(f'3 card.json: placeholder {m.group(0)!r}'); break
    for name in MARKED_FILES:   # 3 editing markers, read as text (the file may no longer parse as JSON)
        fp = d / name
        if not fp.exists(): continue
        for n, line in enumerate(fp.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
            # JSON files: a marker standing alone on its line (outside any value); REPORT.md: a marker outside `code` spans
            m = EDIT_MARKER.fullmatch(line.strip().rstrip(',')) if name.endswith('.json') else EDIT_MARKER.search(re.sub(r'`[^`]*`', '', line))
            if m: pb.append(f'3 {name} line {n}: editing marker {m.group(0)!r} left in the file (finish the edit or rewrite the file)'); break
    # 4 searches
    se = sorted((d / 'searches').glob('*.md')) if (d / 'searches').is_dir() else []
    fu = is_followup(d); smin = int(FOLLOWUP.get('min_searches', 1)) if fu else 3
    if len(se) < smin: pb.append(f'4 searches/: {len(se)} file(s), at least {smin} expected')
    for p in se:
        if not re.search(r'query|search-|citing|references|read ', p.read_text(encoding='utf-8', errors='replace'), re.I):
            pb.append(f'4 {p.name}: no query nor gateway receipt')
    # 5 verdicts
    v = load(d / 'verdicts.json') if (d / 'verdicts.json').exists() else None
    unverified = []
    if v is None: pb.append('5 verdicts.json: missing (downstream verification not done)')
    elif not isinstance(v, dict): pb.append('5 verdicts.json: unreadable JSON' + (f' ({v})' if isinstance(v, ValueError) else ''))
    else:
        st = {a.get('id'): a.get('status') for a in v.get('claims') or []}
        for i in sorted(ids, key=str) if isinstance(f, dict) else []:
            if i not in st: pb.append(f'5 claim {i}: no status in verdicts.json')
        for i, s in st.items():
            if s not in STATUSES: pb.append(f'5 claim {i}: unknown status {s!r}')
            elif s in UNHANDLED: pb.append(f'5 claim {i}: {s} not handled (removal or re-verification): card not deliverable')
            elif s != 'FOUND': unverified.append(i)
    if prior_art:
        import prior_art as _pa
        pb += _pa.problems(d)
    # 6-7-10-11-12 REPORT.md
    if prior_art: pass
    elif not (d / 'REPORT.md').exists(): pb.append('6 REPORT.md: missing')
    else:
        t = (d / 'REPORT.md').read_text(encoding='utf-8', errors='replace')
        pb += report_problems(t, followup=fu, families=SF.by_number(SF.families(f if isinstance(f, dict) else {}, t)))
        if PLACEHOLDER.search(t): pb.append(f'3 REPORT.md: placeholder {PLACEHOLDER.search(t).group(0)!r}')
        if unverified and not UNVERIFIED.search(t): pb.append(f'7 REPORT.md: {len(unverified)} unverified claim(s) not flagged')
    # 8 result.json
    r = load(d / 'result.json') if (d / 'result.json').exists() else None
    if prior_art: pass
    elif r is None: pb.append('8 result.json: missing')
    elif isinstance(r, Exception): pb.append('8 result.json: unreadable JSON')
    else: pb += ['8 result.json: ' + x for x in pb_result(r)]
    # 9 header
    e = load(d / 'run.json') if (d / 'run.json').exists() else None
    if not isinstance(e, dict): pb.append('9 run.json: missing (validate_card.py --header)')
    elif (d / 'state' / 'journal.jsonl').exists() and e.get('calls') != header(d)['calls']:
        pb.append(f'9 run.json: {e.get("calls")} calls declared, {header(d)["calls"]} in the journal')
    return pb


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args: print(__doc__); sys.exit(2)
    d = pathlib.Path(args[0])
    if not d.is_dir(): print(f'validate_card.py: not a directory: {args[0]!r} (a relative path is read from the current directory {pathlib.Path.cwd()})'); sys.exit(2)
    if '--header' in sys.argv:
        if (d / 'state' / 'journal.jsonl').exists():
            (d / 'run.json').write_text(json.dumps(header(d), ensure_ascii=False, indent=1)); print('run.json written')
        else:                                                # injected mode or a copied run: never replace a header by an empty one
            print('run.json not written: no state/journal.jsonl', file=sys.stderr)
    p = problems(d, prior_art='--prior-art' in sys.argv) + end_problems(d); w = warnings(d)
    print('\n'.join(p) if p else 'OK')
    if w: print('\n'.join('warning: ' + x for x in w))
    sys.exit(1 if p else 0)
