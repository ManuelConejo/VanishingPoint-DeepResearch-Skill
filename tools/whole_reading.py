#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Whole reading before verdicts (plugins/code.md, section "Whole reading before verdicts"; SKILL.md section 4).

One reader, one call, no tool, fresh context: Y in full (mechanical condensation of the repository at its SHA, built by
condense_repo.py: tree, then whole text files with line numbers, declared cap) then X in full (whole files at the SHA of the
capsule: the files the searches read or cited `file:line@SHA`, plus the seams of the capsule), under one question (prompts/WHOLE-READING.md).
The output is treated as one more search: searches/whole-reading.md (reader output behind a material header) and
state/whole-reading/{PROMPT.md, material-X.txt, material-X.json, material-Y.txt, launch.json, trace.jsonl, receipt.json}.
No clone, no checkout, no execution of any code of Y or X: git is used read-only (ls-tree, cat-file, show).

Usage:
  whole_reading.py RUN_DIR [--y-repo DIR --y-sha SHA [--y-name NAME] | --y-material FILE]
                   [--x-repo DIR --x-sha SHA [--x-name NAME] [--x-prefix P/]] [--x2-repo DIR --x2-sha SHA [--x2-name NAME] [--x2-prefix P/]]
                   [--T DATE] [--request TEXT] [--target TEXT] [--model M] [--host claude|openai]
                   [--y-cap N] [--x-cap N] [--priority P ...] [--exclude P ...] [--wait SECONDS] [--sync] [--material-only]
  RUN_DIR holds scope.md (X@SHA, Y@SHA, T and the request are read there when not given), searches/*.md, capsule.md and,
  optionally, state/calls.jsonl. Repositories are local git directories (bare or not) already present on the machine.
Behaviour: the first call builds the material without any model, then launches ONE model call in the background and waits
  up to --wait seconds (default 90); it prints a JSON status ("running" | "done" | "failed"). Calling the same command again
  waits again and prints the status; a run is launched once. --sync waits until the call ends. --material-only writes the
  prompt and the material without calling any model.
Model: --model, else VP_MODEL (environment), else the orchestrator's model is unknown to this script and the configured
  default of tools/config.json ("whole_reading.model", else "verifier.model") is used. Host command: tools/config.json
  "model_command"[host] with host = --host, else VP_HOST, else config "host"; profile "claude" = `claude -p` on stdin with no tool,
  profile "openai" = `codex exec` on stdin in an empty read-only directory. VP_MODEL_COMMAND_CLAUDE / VP_MODEL_COMMAND_OPENAI
  (a JSON list) override the command (tests with a fake executable).
"""
import argparse, datetime as dt, hashlib, json, os, pathlib, re, shutil, subprocess, sys, tempfile, time

HERE = pathlib.Path(__file__).resolve().parent
CFG = json.loads((HERE / 'config.json').read_text())
WR = CFG.get('whole_reading', {})
Y_CAP = int(WR.get('y_cap_chars', 400000)); X_CAP = int(WR.get('x_cap_chars', 200000))
MAX_USD = float(WR.get('max_usd', 2.5)); TIMEOUT = int(WR.get('timeout_s', 1500)); WAIT = 90
REF = re.compile(r'(?<![\w/@])((?:[\w.-]+/)*[\w.-]+\.[A-Za-z0-9]{1,8}):(\d+)(?:\s*[-–]\s*(\d+))?@([0-9a-f]{7,40})')
SHA_LINE = re.compile(r'\b(X2|X|Y)\s*[:=]\s*([^\s@,;]+)@([0-9a-f]{7,40})')
T_LINE = re.compile(r'\bT\s*=\s*(\d{4}-\d{2}-\d{2}(?:T[0-9:]+Z?)?)')


def utc(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def chown(p):
    for q in ([p, *p.rglob('*')] if p.is_dir() else [p]):
        try: os.chown(q, 1000, 1000)
        except (PermissionError, FileNotFoundError, OSError): pass


def git(repo, *args):
    p = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, timeout=300)
    return p.returncode, p.stdout


# ------------------------------------------------------------------ X material (whole files at the SHA)
_TREES = {}


def tree(X):
    k = (X['repo'], X['sha'])
    if k not in _TREES:
        rc, out = git(X['repo'], 'ls-tree', '-r', '--name-only', X['sha'], '--', X['prefix'] or '.')
        pre = X['prefix']
        _TREES[k] = [l[len(pre):] if pre and l.startswith(pre) else l for l in out.decode('utf-8', 'replace').splitlines()]
    return _TREES[k]


def resolve(path, X):
    a = tree(X)
    if path in a: return path
    c = [p for p in a if p.endswith('/' + path)]
    return c[0] if len(c) == 1 else None


def seam_block(capsule_text):
    """The target_seam block of the capsule (capsule.md or capsule.json text), up to the next field or heading."""
    m = re.search(r'-?\s*(?:target_seam|couture_visee)\s*:(.*?)(?=\n\s*-?\s*(?:intention|refusals|refus|registry|registre|mode|Y)\s*:|\n## |\Z)', capsule_text, re.S)
    return m.group(1) if m else ''


def x_files(run, xs):
    """Files of X (and X2) to read whole: capsule seams, x-read calls recorded in state/calls.jsonl, file:line@SHA citations of the searches.
    Order: seams first (smallest file first, so more seams fit under the cap), then the other files by number of mentions, then path."""
    count = {}; why = {}

    def add(X, path, motive):
        p = resolve(path, X)
        if not p: return
        k = (X['name'], p); count[k] = count.get(k, 0) + 1; why.setdefault(k, set()).add(motive)

    def by_sha(sha): return next((x for x in xs if x['sha'].startswith(sha)), None)
    cap = ''
    for name in ('capsule.md', 'capsule.json'):
        if (run / name).exists(): cap = (run / name).read_text(errors='replace'); break
    for r in REF.finditer(seam_block(cap)):
        X = by_sha(r.group(4))
        if X: add(X, r.group(1), 'seam')
    calls = run / 'state' / 'calls.jsonl'
    if calls.exists():
        for l in calls.read_text(errors='replace').splitlines():
            try: e = json.loads(l)
            except ValueError: continue
            if e.get('cmd') in ('x-read', 'x-lire') and e.get('args') and e.get('rc', 0) == 0:
                opts = e.get('opts') or {}; rep = opts.get('repo') or opts.get('depot')
                X = xs[0] if rep in (None, xs[0]['name']) else next((x for x in xs[1:] if x['name'] == rep), None)
                if X: add(X, e['args'][0], 'x-read')
    sdir = run / 'searches'
    for f in sorted(sdir.glob('*.md')) if sdir.exists() else []:
        if f.name == 'whole-reading.md': continue
        for r in REF.finditer(f.read_text(errors='replace')):
            X = by_sha(r.group(4))
            if X: add(X, r.group(1), 'citation')

    def size(k):
        X = next(x for x in xs if x['name'] == k[0]); rc, out = git(X['repo'], 'cat-file', '-s', f"{X['sha']}:{X['prefix']}{k[1]}")
        return int(out.decode().strip() or 0) if rc == 0 else 10 ** 9
    seams = sorted([k for k in count if 'seam' in why[k]], key=size)
    others = sorted([k for k in count if 'seam' not in why[k]], key=lambda k: (-count[k], k[1]))
    return [(next(x for x in xs if x['name'] == n), p, count[(n, p)], sorted(why[(n, p)])) for n, p in seams + others]


def x_material(run, xs, x_cap=X_CAP):
    sel = x_files(run, xs); blocks = {}; included = []; excluded = []; total = 0
    for X, p, n, motives in sel:
        rc, data = git(X['repo'], 'show', f"{X['sha']}:{X['prefix']}{p}")
        if rc: excluded.append((X['name'], p, 'absent at the SHA')); continue
        text = data.decode('utf-8', 'replace'); lines = text.splitlines(); s12 = X['sha'][:12]
        if total + len(text) > x_cap: excluded.append((X['name'], p, f'not included (cap {x_cap})')); continue
        total += len(text); included.append((X['name'], p, len(lines), n, motives))
        blocks.setdefault(X['name'], []).append(f'=== {p} @{s12} ({len(lines)} lines) ===\n' + '\n'.join(f'{i}\t{l}' for i, l in enumerate(lines, 1)) + '\n')
    out = []
    for i, X in enumerate(xs):
        s12 = X['sha'][:12]; fs = [f for f in included if f[0] == X['name']]
        out.append(f"# {'X' if i == 0 else 'X2'} = {X['name']}@{s12}" + (f" (prefix {X['prefix']})" if X['prefix'] else '')
                   + f" - {len(fs)} whole files (git show at the SHA), numbered: the files the searches read or cited, plus the seams of the capsule. Expected citation: <path>:<line>@{s12}")
        ex = [e for e in excluded if e[0] == X['name']]
        if ex: out.append('# Not included: ' + ' ; '.join(f'{p} [{r}]' for _, p, r in ex))
        out.append(''); out += blocks.get(X['name'], []); out.append('')
    info = dict(included=[dict(X=a, path=p, lines=l, mentions=n, motives=w) for a, p, l, n, w in included],
                excluded=[dict(X=a, path=p, reason=r) for a, p, r in excluded], chars=total, cap=x_cap)
    return '\n'.join(out), info


# ------------------------------------------------------------------ Y material (condensed repository)
def y_material(d, a):
    if a.y_material:
        text = pathlib.Path(a.y_material).read_text(errors='replace'); src = str(pathlib.Path(a.y_material).name)
    else:
        if not (a.y_repo and a.y_sha): raise SystemExit('Y: give --y-material FILE, or --y-repo DIR --y-sha SHA (read from scope.md when present)')
        out = d / 'material-Y.txt'
        cmd = [sys.executable, '-I', str(HERE / 'condense_repo.py'), '--repo', a.y_repo, '--sha', a.y_sha, '--name', a.y_name or pathlib.Path(a.y_repo).name,
               '--out', str(out), '--cap', str(a.y_cap)]
        if a.priority: cmd += ['--priority', *a.priority]
        if a.exclude: cmd += ['--exclude', *a.exclude]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if r.returncode or not out.exists(): raise SystemExit(f'condense_repo.py failed (rc {r.returncode}): {(r.stderr or r.stdout)[-800:]}')
        text = out.read_text(errors='replace'); src = f"{a.y_name or pathlib.Path(a.y_repo).name}@{a.y_sha[:12]}"
    (d / 'material-Y.txt').write_text(text)
    return text, dict(source=src, chars=len(text), cap=a.y_cap)


# ------------------------------------------------------------------ scope.md reading
def from_scope(run, a):
    s = (run / 'scope.md').read_text(errors='replace') if (run / 'scope.md').exists() else ''
    found = {}
    for m in SHA_LINE.finditer(s): found.setdefault(m.group(1), (m.group(2), m.group(3)))
    if not a.x_sha and 'X' in found: a.x_name = a.x_name or pathlib.Path(found['X'][0]).name; a.x_sha = found['X'][1]; a.x_repo = a.x_repo or found['X'][0]
    if not a.x2_sha and 'X2' in found: a.x2_name = a.x2_name or pathlib.Path(found['X2'][0]).name; a.x2_sha = found['X2'][1]; a.x2_repo = a.x2_repo or found['X2'][0]
    if not a.y_sha and 'Y' in found: a.y_name = a.y_name or found['Y'][0]; a.y_sha = found['Y'][1]
    if not a.T:
        m = T_LINE.search(s); a.T = m.group(1) if m else dt.date.today().isoformat()
    if not a.request:
        m = re.search(r'^(?:Question|Request)[^:\n]*:\s*(.+)$', s, re.M); a.request = (m.group(1).strip().strip('"«» ') if m else '(see scope.md)')
    if not a.target:
        m = re.search(r'^(?:Target|Cible)[^:\n]*:\s*(.+)$', s, re.M); a.target = (m.group(1).strip() if m else (a.x_name or 'X'))
    return a


def x_list(a):
    xs = []
    if a.x_sha:
        if not a.x_repo: raise SystemExit('X: --x-repo DIR is required (local git directory)')
        xs.append(dict(name=a.x_name or pathlib.Path(a.x_repo).name, repo=a.x_repo, sha=a.x_sha, prefix=a.x_prefix or ''))
    if a.x2_sha:
        if not a.x2_repo: raise SystemExit('X2: --x2-repo DIR is required')
        xs.append(dict(name=a.x2_name or pathlib.Path(a.x2_repo).name, repo=a.x2_repo, sha=a.x2_sha, prefix=a.x2_prefix or ''))
    for X in xs:
        rc, out = git(X['repo'], 'rev-parse', '--verify', X['sha'] + '^{commit}')
        if rc: raise SystemExit(f"X: {X['sha']} is not a commit of {X['repo']}")
        X['sha'] = out.decode().strip()
    return xs


def build_prompt(a, y, x):
    g = (HERE / 'prompts' / 'WHOLE-READING.md').read_text()
    for k, v in {'{T}': a.T, '{REQUEST}': a.request, '{TARGET}': a.target, '{Y}': y.rstrip(), '{X}': x.rstrip()}.items(): g = g.replace(k, v)
    assert '{Y}' not in g and '{X}' not in g and '{REQUEST}' not in g
    return g


# ------------------------------------------------------------------ model call (host profiles)
def host_name(a): return a.host or os.environ.get('VP_HOST') or CFG.get('host', 'claude')


def model_name(a): return a.model or os.environ.get('VP_MODEL') or WR.get('model') or CFG.get('verifier', {}).get('model', 'claude-opus-5-5')


def command(host, model):
    env_cmd = os.environ.get('VP_MODEL_COMMAND_' + host.upper())
    base = json.loads(env_cmd) if env_cmd else CFG['model_command'][host]['command']
    argv = [str(x).replace('{model}', model) for x in base]
    if argv and not os.path.isabs(argv[0]) and not shutil.which(argv[0]):  # Codex's login shell may drop ~/.npm-global/bin from PATH
        home = pathlib.Path(os.environ.get('HOME') or '~').expanduser()
        for d in (home / '.npm-global' / 'bin', home / '.local' / 'bin', pathlib.Path('/usr/local/bin')):
            if (d / argv[0]).is_file() and os.access(d / argv[0], os.X_OK): argv[0] = str(d / argv[0]); break
    if host == 'claude':
        if '--output-format' in argv:
            i = argv.index('--output-format'); argv[i + 1] = 'stream-json'
            if '--verbose' not in argv: argv.append('--verbose')
        argv += ['--tools', '', '--max-budget-usd', str(MAX_USD)]
    return argv


def parse_claude(trace):
    res = {}; tools = 0; last = ''
    for line in trace.read_text(errors='replace').splitlines():
        try: e = json.loads(line)
        except ValueError: continue
        if e.get('type') == 'result': res = e
        if e.get('type') == 'assistant':
            for b in ((e.get('message') or {}).get('content') or []):
                if isinstance(b, dict) and b.get('type') == 'tool_use': tools += 1
                if isinstance(b, dict) and b.get('type') == 'text' and b.get('text', '').strip(): last = b['text'].strip()
    txt = (res.get('result') or '').strip() or last  # a max-budget stop may still carry the complete answer in the trace
    u = res.get('usage') or {}
    return txt, dict(usd=res.get('total_cost_usd'), turns=res.get('num_turns'), subtype=res.get('subtype'), tool_calls=tools, usage=u,
                     tokens_in=sum(u.get(k) or 0 for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')),
                     tokens_out=u.get('output_tokens'), recovered_from_trace=not (res.get('result') or '').strip() and bool(last))


def parse_openai(trace):
    txt = ''; cmds = 0; usage = None; errors = []
    for line in trace.read_text(errors='replace').splitlines():
        try: e = json.loads(line)
        except ValueError: continue
        it = e.get('item') or {}
        if e.get('type') == 'item.completed' and it.get('type') == 'agent_message': txt = (it.get('text') or '').strip()
        if it.get('type') == 'command_execution': cmds += 1
        if e.get('type') == 'turn.completed': usage = e.get('usage')
        if e.get('type') in ('error', 'turn.failed'): errors.append(json.dumps(e)[:300])
    u = usage or {}
    return txt, dict(usd=0.0, turns=None, subtype='success' if txt and not errors else 'error', tool_calls=cmds, usage=u, errors=errors,
                     tokens_in=u.get('input_tokens'), tokens_out=u.get('output_tokens'), recovered_from_trace=False)


def execute(run, host, model):
    """Foreground: run the model once on PROMPT.md, write trace.jsonl, searches/whole-reading.md and receipt.json."""
    d = run / 'state' / 'whole-reading'; p = (d / 'PROMPT.md').read_text(); trace = d / 'trace.jsonl'
    env = {k: v for k, v in os.environ.items() if k not in ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN')}
    env['CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS'] = '0'
    argv = command(host, model); cwd = tempfile.mkdtemp(prefix='vp-whole-reading-')  # empty directory: nothing to read there
    t0 = time.monotonic()
    with open(trace, 'w') as out, open(str(trace) + '.err', 'w') as err:
        try: rc = subprocess.run(argv, cwd=cwd, input=p.encode(), stdout=out, stderr=err, env=env, timeout=TIMEOUT).returncode
        except subprocess.TimeoutExpired: rc = -9
        except OSError as e: rc = -1; err.write(str(e))
    shutil.rmtree(cwd, ignore_errors=True)
    txt, m = (parse_claude if host == 'claude' else parse_openai)(trace)
    info = json.loads((d / 'material-X.json').read_text()); yinfo = json.loads((d / 'material-Y.json').read_text())
    header = (f"# searches/whole-reading.md - whole reading before verdicts (single reader, fresh context, no tool, one call, {model} via {host})\n\n"
              f"Material: Y = {yinfo['source']} ({yinfo['chars']} characters, mechanical condensation at the SHA, cap {yinfo['cap']}); X = {len(info['included'])} whole files at the SHA of the capsule: "
              + ', '.join(f"{f['path']} ({f['lines']} l., {'/'.join(f['motives'])})" for f in info['included'])
              + (' ; not included: ' + ', '.join(f"{f['path']} [{f['reason']}]" for f in info['excluded']) if info['excluded'] else '')
              + ". The references below are the reader's: to be verified like any other search.\n\n---\n\n")
    (run / 'searches').mkdir(exist_ok=True)
    if txt: (run / 'searches' / 'whole-reading.md').write_text(header + txt + '\n')
    rec = dict(run=run.name, model=model, host=host, command=argv[:3], rc=rc, seconds=round(time.monotonic() - t0), **m,
               chars=len(txt), words=len(txt.split()), prompt_chars=len(p), prompt_sha256=hashlib.sha256(p.encode()).hexdigest(),
               material_Y=yinfo, material_X=info, output='searches/whole-reading.md' if txt else None, utc=utc())
    (d / 'receipt.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1) + '\n'); chown(run)
    return rec


def alive(pid):
    try: os.kill(pid, 0); return True
    except OSError: return False


def status(run, d, receipt, pidf, wait):
    def done():
        r = json.loads(receipt.read_text())
        return dict(status='done' if r.get('output') else 'failed', file=str(run / 'searches' / 'whole-reading.md') if r.get('output') else None,
                    chars=r.get('chars'), words=r.get('words'), usd=r.get('usd'), rc=r.get('rc'), subtype=r.get('subtype'),
                    files_X=[f['path'] for f in r['material_X']['included']], files_X_not_included=[f['path'] for f in r['material_X']['excluded']],
                    Y=r['material_Y']['source'], note='read searches/whole-reading.md and treat it as one more search (references to verify like the others)')
    t0 = time.time()
    while True:
        if receipt.exists(): return done()
        try: pid = int(pidf.read_text().strip())
        except (ValueError, OSError): pid = 0
        if not alive(pid):
            time.sleep(3)
            if receipt.exists(): return done()
            return dict(status='failed', detail='the reader stopped without a receipt; see state/whole-reading/run.log; do not relaunch, continue without this search')
        if wait is not None and time.time() - t0 >= wait:
            return dict(status='running', detail=f'whole reading in progress (waited {wait} s): call exactly the same command again')
        time.sleep(5)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('run'); ap.add_argument('--y-repo'); ap.add_argument('--y-sha'); ap.add_argument('--y-name'); ap.add_argument('--y-material')
    ap.add_argument('--x-repo'); ap.add_argument('--x-sha'); ap.add_argument('--x-name'); ap.add_argument('--x-prefix', default='')
    ap.add_argument('--x2-repo'); ap.add_argument('--x2-sha'); ap.add_argument('--x2-name'); ap.add_argument('--x2-prefix', default='')
    ap.add_argument('--T'); ap.add_argument('--request'); ap.add_argument('--target'); ap.add_argument('--model'); ap.add_argument('--host', choices=['claude', 'openai'])
    ap.add_argument('--y-cap', type=int, default=Y_CAP); ap.add_argument('--x-cap', type=int, default=X_CAP)
    ap.add_argument('--priority', nargs='*'); ap.add_argument('--exclude', nargs='*')
    ap.add_argument('--wait', type=int, default=WAIT); ap.add_argument('--sync', action='store_true'); ap.add_argument('--material-only', action='store_true')
    ap.add_argument('--execute', action='store_true', help=argparse.SUPPRESS)  # internal: foreground model call in the background process
    a = ap.parse_args(argv)
    run = pathlib.Path(a.run).resolve(); d = run / 'state' / 'whole-reading'; d.mkdir(parents=True, exist_ok=True)
    receipt = d / 'receipt.json'; pidf = d / 'pid'
    if a.execute:
        execute(run, host_name(a), model_name(a)); return 0
    if receipt.exists():
        print(json.dumps(status(run, d, receipt, pidf, 0), ensure_ascii=False)); return 0
    if not pidf.exists():
        a = from_scope(run, a); xs = x_list(a)
        y, yinfo = y_material(d, a); x, info = x_material(run, xs, a.x_cap); p = build_prompt(a, y, x)
        (d / 'PROMPT.md').write_text(p); (d / 'material-X.txt').write_text(x)
        (d / 'material-X.json').write_text(json.dumps(info, ensure_ascii=False, indent=1) + '\n'); (d / 'material-Y.json').write_text(json.dumps(yinfo, ensure_ascii=False) + '\n')
        (d / 'launch.json').write_text(json.dumps(dict(utc=utc(), T=a.T, host=host_name(a), model=model_name(a), prompt_chars=len(p),
                                                       prompt_sha256=hashlib.sha256(p.encode()).hexdigest(), files_X=len(info['included']),
                                                       X=[dict(name=X['name'], sha=X['sha'], prefix=X['prefix']) for X in xs], Y=yinfo), ensure_ascii=False) + '\n')
        chown(d)
        if a.material_only:
            print(json.dumps(dict(status='material', prompt_chars=len(p), files_X=[(f['X'], f['path'], f['lines'], f['mentions'], f['motives']) for f in info['included']],
                                  excluded=info['excluded'], Y=yinfo), ensure_ascii=False)); return 0
        env = dict(os.environ); env.pop('ANTHROPIC_API_KEY', None); env['CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS'] = '0'
        cmd = [sys.executable, '-I', str(HERE / 'whole_reading.py'), str(run), '--execute', '--host', host_name(a), '--model', model_name(a)]
        pr = subprocess.Popen(cmd, cwd=str(run), stdin=subprocess.DEVNULL, stdout=open(d / 'run.log', 'ab'), stderr=subprocess.STDOUT, env=env, start_new_session=True)
        pidf.write_text(str(pr.pid)); chown(d)
    print(json.dumps(status(run, d, receipt, pidf, None if a.sync else a.wait), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
