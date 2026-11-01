"""Licence compatibility of code taken from Y into X (code engine licence-compat, served with plugins/code.md through enabled_by: github):
licence-compat <licence X> <licence Y> [--use link|copy|modify] -> for each use asked (all three without --use): compatible /
compatible_with_conditions (attribution, NOTICE, same licence...) / incompatible / unknown, with the rule applied and its sources (FSF, OSI,
licence texts). X = licence of the receiving project, Y = licence of the code taken; both are SPDX identifiers or expressions with OR / AND
and parentheses ("MIT OR Apache-2.0"). The matrix is DATA: the versioned file named by config.json licence_compat.data
(tools/licence_compat.json: licences, deprecated aliases, groups, rules, conditions, sources); this module holds no verdict of its own.
A pair, licence, use or expression the file does not cover is `unknown`, never `compatible` by default. Every answer opens with the
disclaimer of the file (not legal advice). No network: access `local` (a file of the skill)."""
import hashlib, json, pathlib, re
from sources._common import CFG, date_upper

LC = CFG['licence_compat']
DATA = pathlib.Path(__file__).resolve().parent.parent / LC['data']
VERDICTS = ('compatible', 'compatible_with_conditions', 'unknown', 'incompatible')
RANK = {'compatible': 3, 'compatible_with_conditions': 2, 'unknown': 1, 'incompatible': 0}   # OR on Y keeps the best option, AND the worst
TOKEN = re.compile(r'\(|\)|[A-Za-z0-9][A-Za-z0-9.+-]*')
USE_TYPED = re.compile(r'(?:(?<=\s)|^)use:(\S+)(?=\s|$)', re.I)


class MatrixError(ValueError):
    """The data file is malformed: unknown licence, group, condition or source, or two rules covering the same (Y, X, use)."""


def load(path=None):
    """The data file, checked and expanded: {'raw', 'sha256', 'canon' (lower-case id or alias -> SPDX id), 'cells' {(Y, X, use): rule}}."""
    p = pathlib.Path(path or DATA)
    b = p.read_bytes(); d = json.loads(b)
    lic, groups = d['licences'], d['groups']
    canon = {k.lower(): k for k in lic}
    for a, t in d.get('aliases', {}).items():
        if t not in lic: raise MatrixError(f'alias {a} -> unknown licence {t}')
        canon[a.lower()] = t

    def expand(names, rid):
        out = []
        for n in names:
            if n.startswith('@'):
                if n[1:] not in groups: raise MatrixError(f'rule {rid}: unknown group {n}')
                out += groups[n[1:]]
            else: out.append(n)
        bad = [x for x in out if x not in lic]
        if bad: raise MatrixError(f'rule {rid}: unknown licence(s) {bad}')
        return out
    cells = {}
    for r in d['rules']:
        rid = r.get('id')
        if r.get('verdict') not in VERDICTS or r['verdict'] == 'unknown': raise MatrixError(f'rule {rid}: verdict must be one of {VERDICTS[:2] + VERDICTS[3:]}')
        if [c for c in r.get('conditions', []) if c not in d['conditions']]: raise MatrixError(f'rule {rid}: unknown condition')
        if r['verdict'] == 'compatible_with_conditions' and not r.get('conditions'): raise MatrixError(f'rule {rid}: conditions required')
        if not r.get('sources') or [s for s in r['sources'] if s not in d['sources']]: raise MatrixError(f'rule {rid}: sources missing or unknown')
        if [u for u in r['use'] if u not in d['uses']]: raise MatrixError(f'rule {rid}: unknown use')
        for y in expand(r['y'], rid):
            for x in expand(r['x'], rid):
                for u in r['use']:
                    if (y, x, u) in cells: raise MatrixError(f'rules {cells[(y, x, u)]["id"]} and {rid} both cover {y} -> {x} ({u})')
                    cells[(y, x, u)] = r
    return {'raw': d, 'sha256': hashlib.sha256(b).hexdigest(), 'canon': canon, 'cells': cells, 'file': str(p.relative_to(DATA.parent.parent)) if p.is_relative_to(DATA.parent.parent) else p.name}


def parse(tokens, i=0):
    """SPDX expression over tokens from position i: expr := term (OR term)* ; term := factor (AND factor)* ; factor := ID [WITH ID] | ( expr ).
    -> (tree, next position). Tree: ('id', text) | ('or', [...]) | ('and', [...]). Raises ValueError on a malformed expression."""
    def factor(i):
        if i >= len(tokens): raise ValueError('expression ends early')
        t = tokens[i]
        if t == '(':
            e, i = expr(i + 1)
            if i >= len(tokens) or tokens[i] != ')': raise ValueError('unbalanced parenthesis')
            return e, i + 1
        if t == ')' or t.upper() in ('OR', 'AND', 'WITH'): raise ValueError(f'licence identifier expected, got {t!r}')
        if i + 1 < len(tokens) and tokens[i + 1].upper() == 'WITH':
            if i + 2 >= len(tokens): raise ValueError('exception identifier expected after WITH')
            return ('id', f'{t} WITH {tokens[i + 2]}'), i + 3
        return ('id', t), i + 1

    def term(i):
        parts = []
        e, i = factor(i); parts.append(e)
        while i < len(tokens) and tokens[i].upper() == 'AND':
            e, i = factor(i + 1); parts.append(e)
        return (parts[0] if len(parts) == 1 else ('and', parts)), i

    def expr(i):
        parts = []
        e, i = term(i); parts.append(e)
        while i < len(tokens) and tokens[i].upper() == 'OR':
            e, i = term(i + 1); parts.append(e)
        return (parts[0] if len(parts) == 1 else ('or', parts)), i
    return expr(i)


def text(tree):
    k, v = tree
    if k == 'id': return v
    return '(' + f' {k.upper()} '.join(text(x) for x in v) + ')'


def split_args(arg):
    """'<X> <Y>' where each side is an SPDX expression -> (X tree, Y tree): X is read greedily (an identifier not preceded by OR / AND
    starts Y). Raises ValueError when the argument is not exactly two expressions."""
    arg = re.sub('["\']', ' ', arg)                                       # quotes around an expression are not part of it
    toks = TOKEN.findall(arg)
    if ''.join(toks) != re.sub(r'\s+', '', arg): raise ValueError('characters outside SPDX identifiers, OR, AND, WITH and parentheses')
    x, i = parse(toks)
    if i >= len(toks): raise ValueError('two licences expected: <licence X> <licence Y>')
    y, j = parse(toks, i)
    if j != len(toks): raise ValueError(f'unexpected text after the licence of Y: {" ".join(toks[j:])!r}')
    return x, y


def _leaf(M, y, x, use, T):
    """One SPDX identifier of Y against one of X for one use -> answer dict (rule and sources, or unknown with its reason)."""
    d = M['raw']; cy, cx = M['canon'].get(y.lower()), M['canon'].get(x.lower())
    base = {'y': y, 'x': x, 'use': use}
    unknown = [n for n, c in ((y, cy), (x, cx)) if c is None]
    if unknown: return dict(base, verdict='unknown', reason=f'licence not in the table: {", ".join(unknown)} (SPDX identifiers known: see data file)')
    for c in (cy, cx):
        pub = d['licences'][c].get('published')
        if pub and T and (date_upper(pub) is None or date_upper(pub) >= T):
            return dict(base, y=cy, x=cx, verdict='unknown', reason=f'{c} was not published before T ({pub})')
    r = M['cells'].get((cy, cx, use))
    if r is None: return dict(base, y=cy, x=cx, verdict='unknown', reason='no rule in the table for this pair and use: nothing is concluded')
    return dict(base, y=cy, x=cx, verdict=r['verdict'], rule=r['id'], conditions=list(r.get('conditions', [])),
                sources=list(r['sources']), **({'note': r['note']} if r.get('note') else {}),
                **({'alias': {k: v for k, v in ((y, cy), (x, cx)) if k != v}} if (y, x) != (cy, cx) else {}))


def _combine(kind, parts, side):
    """OR on Y: the best option (the user may choose it); AND (either side) and OR on X (X keeps every option only if each is honoured): the
    worst. -> answer with `options` listing every part; conditions of the retained part(s)."""
    if kind == 'or' and side == 'y':
        best = max(parts, key=lambda a: RANK[a['verdict']])
        return {'verdict': best['verdict'], 'combined_as': 'Y offered under several licences: the best option is retained (choose it explicitly)',
                'retained': best.get('y_expr', best.get('y')), 'conditions': best.get('conditions', []), 'options': parts}
    worst = min(parts, key=lambda a: RANK[a['verdict']])
    conds = [] if worst['verdict'] in ('incompatible', 'unknown') else sorted({c for a in parts for c in a.get('conditions', [])})
    how = ('X offered under several licences: every option must be honoured to keep them all (an incompatible option must be dropped from X)'
           if kind == 'or' else 'licences that apply together (AND): every one must be honoured')
    return {'verdict': worst['verdict'], 'combined_as': how, 'conditions': conds, 'options': parts}


def evaluate(M, xt, yt, use, T):
    """Tree of X, tree of Y -> answer for one use (recursive over OR / AND)."""
    if yt[0] != 'id':
        parts = [dict(evaluate(M, xt, p, use, T), y_expr=text(p)) for p in yt[1]]
        return _combine(yt[0], parts, 'y')
    if xt[0] != 'id':
        parts = [dict(evaluate(M, p, yt, use, T), x_expr=text(p)) for p in xt[1]]
        return _combine(xt[0], parts, 'x')
    return _leaf(M, yt[1], xt[1], use, T)


def _explain(M, a):
    """Condition codes and source ids expanded to their texts (data file), recursively in options."""
    d = M['raw']
    out = dict(a)
    if a.get('conditions'): out['conditions'] = [{'code': c, 'text': d['conditions'][c]} for c in a['conditions']]
    if a.get('sources'): out['sources'] = [dict(d['sources'][s], id=s) for s in a['sources']]
    if a.get('options'): out['options'] = [_explain(M, o) for o in a['options']]
    return out


def run_licence_compat(g, arg, n, opt, B, extra):
    """licence-compat <licence X> <licence Y> [--use link|copy|modify] (use: may also be typed in the argument)."""
    M = load()
    d = M['raw']
    uses = [m.group(1).lower() for m in USE_TYPED.finditer(arg)]
    if opt.get('use'): uses.append(str(opt['use']).lower())
    if len(set(uses)) > 1: return {'refusal': f'licence-compat: use given twice with two values ({", ".join(sorted(set(uses)))})'}
    if uses and uses[0] not in d['uses']: return {'refusal': f'licence-compat: use must be one of {", ".join(d["uses"])}'}
    try: xt, yt = split_args(USE_TYPED.sub(' ', arg))
    except ValueError as e: return {'refusal': f'licence-compat: {e}; expected <licence X> <licence Y> (SPDX identifiers or expressions, e.g. <X> "<A> OR <B>")'}
    asked = uses[:1] or list(d['uses'])
    answers = [dict(_explain(M, evaluate(M, xt, yt, u, B.T)), use=u) for u in asked]
    return {'disclaimer': d['disclaimer'], 'direction': d['direction'], 'x': text(xt), 'y': text(yt),
            'answers': answers, 'verdicts': d['verdicts'], 'uses': {u: d['uses'][u] for u in asked},
            'data': {'file': M['file'], 'schema': d['schema'], 'version': d['version'], 'date': d['date'], 'sha256': M['sha256']},
            'cite': f"VanishingPoint licence table {d['version']} ({d['date']}, sha256 {M['sha256'][:12]}): rule ids in answers[].rule, sources in answers[].sources",
            'date': d['date'], 'as_of': f"table dated {d['date']}; licences published on/after T are answered unknown"}


SOURCE = {
    'name': 'licence-compat', 'order': 48,
    'enabled_by': ('github',),                                         # plugins/code.md declares `github` (licence rule): served with the code plugin
    'commands': {'licence-compat': {'engine': 'licence-compat', 'run': run_licence_compat, 'date_filter': False, 'example': 'MIT Apache-2.0 --use copy'}},
    'plugins': ('code',), 'access': 'local',
    'terms': 'no network: reads the versioned table of the skill (config.json licence_compat.data); the rules cite the FSF, the OSI, the licence stewards '
             'and the licence texts',
    'barrier': 'a licence published on/after T is answered unknown (licences[].published of the table); the table itself is dated (data.date)',
    'as_of': 'the date of the table (data.date)',
}
