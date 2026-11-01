#!/usr/bin/env python3
"""Repository map for the selection of the files of Y under the cap (tools/condense_repo.py, option selection = "repo-map").

Idea taken from Aider (aider/repomap.py): every file gives tags (the identifiers it DEFINES and the identifiers it REFERENCES), the files
form a graph (an edge from the file that references an identifier to the files that define it, weighted by the references), a PageRank
personalised on the files and identifiers named in the request / the searches / the capsule ranks the files, and the files are taken by
decreasing score until the budget. Differences from Aider, all deliberate: the files stay WHOLE with git line numbers (only the order of
the candidates changes, condense_repo keeps its cap rule), no LLM, no token budget, standard library only (Python >= 3.9):
  - Python: `ast` (parse only, nothing is imported or executed); a file that does not parse falls back to the regular expressions;
  - JS/TS, Go, Rust, Java/Kotlin/Scala/C#, C/C++: tags by regular expressions (declarations only; every identifier token is a reference);
  - the stem of a file name (budget.py -> `budget`; `__init__`, `index`, `mod`... -> the directory name) is a definition: an import of
    a module is a reference to its file; only for a file that has at least one definition of its own (an empty `__init__.py`, a file that
    only re-exports, defines nothing: it receives no definition mass; config stem_needs_definition);
  - the PageRank is written here (power iteration, fixed order of the nodes: the result is deterministic).
Every constant is read from tools/config.json condense.repo_map (the values are Aider's, none measured in this skill: that is what the
internal duel measures). Nothing of Y is executed.

API: score_files(paths, read, mentions, params) -> (scores {path: float}, stats); mentions_from_run(run_dir, y_sha) -> {"idents", "paths"}.
CLI (inspection): repo_map.py --repo DIR --sha SHA [--run RUN_DIR] [--top 30]
"""
import argparse, ast, collections, json, math, pathlib, re, sys, warnings

HERE = pathlib.Path(__file__).resolve().parent
CFG = json.loads((HERE / 'config.json').read_text()).get('condense', {})
PARAMS = CFG.get('repo_map') or {}

IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
# Keywords of the grammars: never the name of a declaration (the regular expressions of methods and C functions would catch them).
NOT_A_NAME = frozenset('if for while switch catch return else do sizeof function new delete typeof elif with try finally case default '
                       'defined throw await yield match using lock foreach unless until'.split())
S = r'[A-Za-z_$][\w$]*'
JS = [re.compile(p, re.M) for p in (
    r'\b(?:function\*?|class|interface|enum|namespace)\s+(' + S + ')',
    r'\btype\s+(' + S + r')\s*(?:<[^=\n]*>)?\s*=',
    r'\b(?:const|let|var)\s+(' + S + r')\s*(?::[^=\n]+)?=\s*(?:async\s*)?(?:function|\([^)]*\)\s*(?::[^=\n]+)?=>|' + S + r'\s*=>)',
    r'^\s*export\s+(?:default\s+)?(?:const|let|var)\s+(' + S + ')',
    r'^\s+(?:(?:public|private|protected|static|async|readonly|get|set|override)\s+)*(' + S + r')\s*(?:<[^>\n]*>)?\([^)\n]*\)\s*(?::\s*[^{;\n]+)?\{')]
GO = [re.compile(p, re.M) for p in (r'^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)', r'^type\s+([A-Za-z_]\w*)', r'^\s*(?:const|var)\s+([A-Za-z_]\w*)\s')]
RS = [re.compile(p, re.M) for p in (r'\bfn\s+([A-Za-z_]\w*)', r'\b(?:struct|enum|trait|type|mod|const|static|union)\s+([A-Za-z_]\w*)',
                                   r'\bmacro_rules!\s*([A-Za-z_]\w*)')]
JVM = [re.compile(p, re.M) for p in (
    r'\b(?:class|interface|enum|record|object|trait)\s+([A-Za-z_]\w*)',
    r'\bfun\s+(?:<[^>]*>\s*)?(?:[\w.]+\.)?([A-Za-z_]\w*)\s*\(',
    r'^\s*(?:(?:public|private|protected|static|final|abstract|synchronized|native|override|virtual|async|internal|open|suspend)\s+)+[\w<>\[\],.? ]+?\s+([A-Za-z_]\w*)\s*\(')]
C = [re.compile(p, re.M) for p in (
    r'\b(?:struct|class|enum|union|namespace)\s+([A-Za-z_]\w*)', r'^\s*#\s*define\s+([A-Za-z_]\w*)',
    r'\btypedef\b[^;{]*?\b([A-Za-z_]\w*)\s*;',
    r'^[A-Za-z_][\w\s\*&:<>,~]*?[\s\*&:]([A-Za-z_~][\w:~]*)\s*\([^;{)]*\)\s*(?:const\s*)?(?:noexcept\s*)?\{')]
PY_FALLBACK = [re.compile(r'^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)', re.M)]
LANG = {}
for exts, pats in ((('js', 'jsx', 'mjs', 'cjs', 'ts', 'tsx', 'mts', 'cts'), JS), (('go',), GO), (('rs',), RS),
                   (('java', 'kt', 'kts', 'scala', 'cs'), JVM), (('c', 'h', 'cc', 'cpp', 'cxx', 'hh', 'hpp', 'hxx'), C)):
    for e in exts: LANG[e] = pats


def ext(path):
    name = path.rsplit('/', 1)[-1]
    return name.rsplit('.', 1)[-1].lower() if '.' in name else ''


def stem(path, package_stems):
    parts = path.split('/'); name = parts[-1]; s = name.rsplit('.', 1)[0] if '.' in name else name
    if s in package_stems and len(parts) > 1: return parts[-2]
    return s


def python_tags(text):
    """-> (defs set, refs Counter) by `ast` (parse only); None when the file does not parse."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    defs = set(); refs = collections.Counter()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): defs.add(n.name)
        elif isinstance(n, ast.Name):
            refs[n.id] += 1
        elif isinstance(n, ast.Attribute): refs[n.attr] += 1
        elif isinstance(n, ast.ImportFrom):
            for a in n.names: refs[a.name.rsplit('.', 1)[-1]] += 1
            if n.module: refs[n.module.rsplit('.', 1)[-1]] += 1
        elif isinstance(n, ast.Import):
            for a in n.names: refs[a.name.rsplit('.', 1)[-1]] += 1
    for n in tree.body:                                   # module-level constants and aliases are definitions
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, (ast.AnnAssign, ast.AugAssign)) else []
        for t in targets:
            if isinstance(t, ast.Name) and not (t.id.startswith('__') and t.id.endswith('__')): defs.add(t.id)   # __all__, __version__...: module metadata, not a definition
    return defs, refs


def file_tags(path, text, package_stems, stem_needs_definition=True):
    """-> (defs set, refs Counter) of one file. Unknown extensions (documents, data): no tag, the file is only a node of the graph."""
    e = ext(path); defs = set(); refs = collections.Counter()
    if e in ('py', 'pyi'):
        t = python_tags(text)
        if t is None:
            for p in PY_FALLBACK: defs.update(m.group(1) for m in p.finditer(text))
            refs.update(IDENT.findall(text))
        else: defs, refs = t
    elif e in LANG:
        for p in LANG[e]: defs.update(m.group(1) for m in p.finditer(text))
        refs.update(IDENT.findall(text))
    else: return set(), collections.Counter()
    defs = {d for d in defs if d not in NOT_A_NAME}
    if defs or not stem_needs_definition: defs.add(stem(path, package_stems))   # a module name is a definition only for a file that defines something
    return defs, refs


def is_well_named(name, min_len):
    snake = '_' in name.strip('_') and name == name.lower(); camel = bool(re.search(r'[a-z][A-Z]', name)); kebab = '-' in name
    return len(name) >= min_len and (snake or camel or kebab)


# ------------------------------------------------------------------ mentions (request, searches, capsule)
URL = re.compile(r'https?://\S+')
PATHLIKE = re.compile(r'(?<![\w/.-])((?:[\w.-]+/)+[\w.-]+|[\w-]+\.(?:py|pyi|js|jsx|mjs|cjs|ts|tsx|go|rs|java|kt|scala|cs|c|h|cc|cpp|hpp))(?![\w/-])')
REF = re.compile(r'(?<![\w/@])((?:[\w.-]+/)*[\w-][\w.-]*):(\d+)(?:\s*[-–]\s*(\d+))?@([0-9a-f]{7,40})')
BACKTICK = re.compile(r'`([^`\n]{1,200})`')


def mentions_from_text(text, y_sha=None, min_len=4):
    """Identifiers and paths named in a text. Paths: `file:line@SHA` references whose SHA is Y's (a reference to X is not a path of Y),
    and path-like tokens without a SHA. Identifiers: every identifier inside backticks, and the code-like words of the prose (an
    underscore inside, or a lower-case letter followed by a capital): plain words are not identifiers."""
    idents = set(); paths = set()
    for m in REF.finditer(text):
        sha = m.group(4)
        if y_sha is None or y_sha.startswith(sha) or sha.startswith(y_sha): paths.add(m.group(1))
    text = REF.sub(' ', text); text = URL.sub(' ', text)
    paths.update(m.group(1) for m in PATHLIKE.finditer(text))
    for m in BACKTICK.finditer(text): idents.update(w for w in IDENT.findall(m.group(1)) if len(w) >= min_len)
    for w in IDENT.findall(text):
        if len(w) >= min_len and ('_' in w.strip('_') or re.search(r'[a-z][A-Z]', w)): idents.add(w)
    return idents, paths


def mentions_from_run(run, y_sha=None, min_len=None):
    """Mentions of a run directory: scope.md, searches/*.md (not whole-reading.md, which is this tool's own output), capsule.md. The capsule
    describes the target X, not Y: unless config capsule_paths_anchor, it gives identifiers only (they anchor a file only if Y defines them)."""
    run = pathlib.Path(run); min_len = int(min_len or PARAMS.get('mention_min_len', 4))
    files = [run / 'scope.md', run / 'capsule.md'] + sorted((run / 'searches').glob('*.md') if (run / 'searches').is_dir() else [])
    idents = set(); paths = set()
    for f in files:
        if f.name == 'whole-reading.md' or not f.is_file(): continue
        i, p = mentions_from_text(f.read_text(errors='replace'), y_sha, min_len); idents |= i
        if f.name != 'capsule.md' or PARAMS.get('capsule_paths_anchor', False): paths |= p
    return {'idents': sorted(idents), 'paths': sorted(paths)}


# ------------------------------------------------------------------ PageRank
def pagerank(nodes, edges, personalization, damping, iterations, tolerance):
    """Power iteration on a weighted directed graph. nodes: sorted list; edges: {u: {v: weight}}; personalization: {node: mass} (sums to 1;
    it is also where the random surfer restarts and where the mass of the nodes without out-edge goes). Deterministic: fixed node order."""
    x = dict(personalization)
    for _ in range(int(iterations)):
        new = {v: (1 - damping) * personalization[v] for v in nodes}; dangling = 0.0
        for u in nodes:
            out = edges.get(u); tot = sum(out.values()) if out else 0.0
            if tot <= 0: dangling += x[u]; continue
            for v in sorted(out): new[v] += damping * x[u] * out[v] / tot
        for v in nodes: new[v] += damping * dangling * personalization[v]
        diff = sum(abs(new[v] - x[v]) for v in nodes); x = new
        if diff < tolerance: break
    return x


def score_files(paths, read, mentions=None, params=None, sizes=None):
    """paths: the candidate files of Y; read(path) -> bytes or None (None / unreadable: the file is a node without tag).
    mentions: {"idents": [...], "paths": [...]} or None. sizes: {path: bytes}, used only when size_exponent > 0.
    -> (scores {path: float}, stats {...}). The score is the PageRank mass of the file (size_exponent 0, Aider's rule: its tags are small and a
    token budget cuts the list); with size_exponent e > 0 it is divided by max(bytes, 1)**e, the ranking by density of a greedy knapsack
    (the files stay whole, so a very large central file, a generated one for example, takes the whole budget at e = 0)."""
    P = dict(PARAMS); P.update(params or {})
    min_len = int(P.get('ident_min_len', 3)); pstems = set(P.get('package_stems') or ())
    paths = sorted(paths); mentions = mentions or {}
    m_idents = set(mentions.get('idents') or ()); m_paths = list(mentions.get('paths') or ())
    defines = collections.defaultdict(set); refs = {}
    for p in paths:
        data = read(p)
        if data is None: continue
        d, r = file_tags(p, data.decode('utf-8', 'replace'), pstems, bool(P.get('stem_needs_definition', True)))
        for name in d:
            if len(name) >= min_len: defines[name].add(p)
        refs[p] = r
    referenced = collections.defaultdict(dict)           # identifier -> {file: references}, only for the identifiers someone defines
    for p in paths:
        for name, c in refs.get(p, {}).items():
            if name in defines: referenced[name][p] = c
    edges = collections.defaultdict(dict); n_edges = 0
    for name in sorted(defines):
        definers = sorted(defines[name])
        if len(definers) > int(P.get('max_definers', 60)): continue
        mul = 1.0
        if name in m_idents: mul *= float(P.get('mentioned_mul', 10))
        if is_well_named(name, int(P.get('well_named_min_len', 8))): mul *= float(P.get('well_named_mul', 10))
        if name.startswith('_'): mul *= float(P.get('private_mul', 0.1))
        if len(definers) >= int(P.get('common_min_files', 6)): mul *= float(P.get('common_mul', 0.1))
        for p in sorted(referenced.get(name, ())):
            c = referenced[name][p]
            for d in definers:
                if d != p: edges[p][d] = edges[p].get(d, 0.0) + mul * math.sqrt(c); n_edges += 1
    # personalisation anchors: a file of Y named by a path that identifies it (the whole path, or a suffix of at least path_min_components
    # components: `cli.py` alone names nothing), and the files that DEFINE a named identifier (an identifier defined nowhere in Y anchors nothing)
    named = set(); kmin = int(P.get('path_min_components', 2))
    for q in m_paths:
        q = q.strip('/'); k = q.count('/') + 1
        named.update(p for p in paths if p == q or (k >= kmin and p.endswith('/' + q)))
    for i in m_idents: named.update(defines.get(i, ()))
    n = len(paths); share = float(P.get('personal_share', 0.9)) if named else 0.0
    pers = {p: (1 - share) / n + (share / len(named) if p in named else 0.0) for p in paths} if n else {}
    scores = pagerank(paths, edges, pers, float(P.get('damping', 0.85)), P.get('iterations', 100), float(P.get('tolerance', 1e-9))) if n else {}
    stats = dict(files=n, tagged=sum(1 for p in paths if refs.get(p)), defined_identifiers=len(defines), edges=n_edges,
                 mentioned_identifiers=len(m_idents), mentioned_identifiers_defined=sum(1 for i in m_idents if i in defines),
                 mentioned_paths=len(m_paths), personalised_files=len(named))
    e = float(P.get('size_exponent', 0))
    if e > 0 and sizes: scores = {p: s / max(sizes.get(p, 1), 1) ** e for p, s in scores.items()}
    stats['size_exponent'] = e
    return {p: round(s, 18) for p, s in scores.items()}, stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--repo', required=True); ap.add_argument('--sha', required=True)
    ap.add_argument('--run', help='run directory: scope.md, searches/*.md, capsule.md name the files and identifiers to personalise on')
    ap.add_argument('--top', type=int, default=30)
    a = ap.parse_args()
    sys.path.insert(0, str(HERE)); import condense_repo as cr
    rd = cr.LocalRepo(a.repo); sha = rd.resolve(a.sha)
    paths = [p for p, _ in rd.tree(sha) if cr.exclusion_reason(p, ()) is None]
    ment = mentions_from_run(a.run, sha) if a.run else None
    scores, stats = score_files(paths, lambda p: rd.blob(sha, p), ment)
    print(json.dumps(stats))
    for p in sorted(scores, key=lambda p: (-scores[p], p))[:a.top]: print(f'{scores[p]:.6f}  {p}')


if __name__ == '__main__': main()
