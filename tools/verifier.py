#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Wrapper of the VanishingPoint level-1 verifier. Takes a report (card of claims) + its sources, returns each claim with a status.

Role instructions and citation check live next to this file and are used in place:
  verifier/ROLE.md             role instructions, copied as is into the working directory of the call
  verifier/citation_check.py   mechanical check of the fragments (import)
  verifier/fetch_fulltext.py   open-access full text retrieval (--fulltext)
Measured on our benches (n = 50 questions, downstream): -4.2 points of false claims (CI 97.5 [-7.1; -1.5]); hardened set: 81/81.

Command line:
  verifier.py verify --card card.json --out verdicts.json [--sources DIR] [--T YYYY-MM-DD --plugin P.md ...] [--fulltext]
                     [--model M] [--host claude|openai] [--mode auto|card|source] [--work DIR] [--filter]
  verifier.py check verdicts.json SOURCES_DIR          (citation_check.py)
Import:
  from verifier import verify, load_sources, filter_claims, model_call
  res = verify(card, texts, engine=model_call)         # engine: callable(prompt, workdir) -> (json_text, measure)

Card: card.json (claims[].source.key -> card.sources[key] = {doi|arxiv|pmid|pmcid, title}).
Sources: DIR/<KEY>/source.txt (full text); otherwise, with --T, record + dated abstract through the gateway (a claim
about a point the abstract does not cover is then ABSENT); otherwise SOURCE-UNAVAILABLE.
Statuses: FOUND | DISTORTED | ABSENT | SOURCE-UNAVAILABLE | INVALID (fragments not found after one retry) | UNVERIFIED (call failed).

Model call: tools/config.json "model_command"[host] (host = env VP_HOST, else config "host", default claude); the command list
can be overridden by env VP_MODEL_COMMAND_CLAUDE / VP_MODEL_COMMAND_OPENAI (a JSON list), e.g. to point at a fake executable.
"""
import argparse, json, os, pathlib, re, shutil, subprocess, sys, tempfile, time

HERE = pathlib.Path(__file__).resolve().parent
ROLE_DIR = HERE / 'verifier'
ROLE_FILE = ROLE_DIR / 'ROLE.md'
sys.path.insert(0, str(ROLE_DIR))
from citation_check import check, norm, load_texts     # noqa: E402

try:
    CONFIG = json.loads((HERE / 'config.json').read_text(encoding='utf-8'))
except (OSError, ValueError):
    CONFIG = {}
CFG = CONFIG.get('verifier', {})
MAX_CHARS = int(CFG.get('max_chars_per_call', 200000))  # above: split per source (threshold to be measured, not a reference value)
TIMEOUT = int(CFG.get('timeout_s', 1200))


def default_model(host):
    """Model of the verifier for a host profile: VP_MODEL, else tools/config.json verifier.model[host] (a string applies to the
    claude profile only), else '' = the host CLI's own default. No model name is fixed in the code."""
    if os.environ.get('VP_MODEL'): return os.environ['VP_MODEL']
    m = CFG.get('model')
    if isinstance(m, dict): return str(m.get(host) or '')
    return str(m or '') if host == 'claude' else ''


def strip_model(argv):
    """Without a model name the host CLI decides: drop `--model ''` / `-m ''` left by the template."""
    out, skip = [], False
    for i, x in enumerate(argv):
        if skip: skip = False; continue
        if x in ('--model', '-m') and i + 1 < len(argv) and argv[i + 1] == '': skip = True; continue
        out.append(x)
    return out
TOOLS_OK = 'Read Grep Glob'
TOOLS_NO = 'Bash Write Edit NotebookEdit WebFetch WebSearch Task Agent'
DEFAULT_MODEL_COMMAND = {
    'claude': {'command': ['claude', '-p', '--model', '{model}', '--output-format', 'json', '--no-session-persistence'], 'stdin': True},
    'openai': {'command': ['codex', 'exec', '-m', '{model}', '-s', 'read-only', '--skip-git-repo-check', '--ephemeral', '-c', 'web_search="disabled"',
                           '-c', 'tools.web_search=false', '--color', 'never', '--json', '-'], 'stdin': True}}
PROMPT = ('Read ROLE.md then apply it to card.json with the sources of the sources/ directory '
          '(sources/<KEY>/source.txt). Read nothing else. Answer only with the requested JSON.')
ABSTRACT_NOTE = ('\n\n---\nNote: for the sources marked "(record + abstract)", the source provided is NOT the full text. '
                 'A claim about an element the abstract does not cover is ABSENT.')
STATUSES = ['FOUND', 'DISTORTED', 'ABSENT', 'SOURCE-UNAVAILABLE', 'INVALID', 'UNVERIFIED']
UNSUPPORTED = {'DISTORTED', 'ABSENT', 'INVALID'}
NO_ABSTRACT = re.compile(r'^\s*\(no abstract', re.I)


def extract_json(text):
    m = re.search(r'\{.*\}', text or '', re.S)
    if not m: return None
    try: return json.loads(m.group(0))
    except json.JSONDecodeError: return None


def host_name(host=None):
    return host or os.environ.get('VP_HOST') or CONFIG.get('host') or 'claude'


def model_command(host):
    """Command list for the host profile: env VP_MODEL_COMMAND_<HOST> (JSON list), else config model_command[host], else built-in default."""
    raw = os.environ.get(f'VP_MODEL_COMMAND_{host.upper()}')
    if raw:
        cmd = json.loads(raw)
        if not isinstance(cmd, list) or not all(isinstance(x, str) for x in cmd): raise RuntimeError(f'VP_MODEL_COMMAND_{host.upper()}: a JSON list of strings is expected')
        return cmd
    prof = (CONFIG.get('model_command') or {}).get(host) or DEFAULT_MODEL_COMMAND.get(host)
    if not prof: raise RuntimeError(f'unknown host profile: {host!r} (expected claude or openai)')
    return resolve_executable(list(prof['command']))


def resolve_executable(cmd):
    """Replace cmd[0] by an absolute path when it is not on PATH: Codex runs tools through a login shell whose PATH may drop the
    directory of its own binary (seen with `~/.npm-global/bin` in a container). Candidates: ~/.npm-global/bin, ~/.local/bin, /usr/local/bin."""
    if not cmd or os.path.isabs(cmd[0]) or shutil.which(cmd[0]): return cmd
    home = pathlib.Path(os.environ.get('HOME') or '~').expanduser()
    for d in (home / '.npm-global' / 'bin', home / '.local' / 'bin', pathlib.Path('/usr/local/bin')):
        p = d / cmd[0]
        if p.is_file() and os.access(p, os.X_OK): return [str(p)] + cmd[1:]
    return cmd


def _parse_claude(stdout):
    out = json.loads(stdout)
    u = out.get('usage', {})
    return out.get('result', ''), {'cost_usd': out.get('total_cost_usd', 0) or 0,
                                   'tokens_in': (u.get('input_tokens', 0) or 0) + (u.get('cache_read_input_tokens', 0) or 0) + (u.get('cache_creation_input_tokens', 0) or 0),
                                   'tokens_out': u.get('output_tokens', 0) or 0, 'turns': out.get('num_turns')}


def _parse_codex(stdout):
    """`codex exec --json` event stream: the text is the last item.completed whose item.type == agent_message; usage in turn.completed."""
    text, tin, tout, turns = None, 0, 0, 0
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith('{'): continue
        try: ev = json.loads(line)
        except json.JSONDecodeError: continue
        t = ev.get('type')
        if t == 'item.completed' and (ev.get('item') or {}).get('type') == 'agent_message':
            text = ev['item'].get('text', '')
        elif t == 'turn.completed':
            u = ev.get('usage') or {}
            tin += (u.get('input_tokens', 0) or 0) + (u.get('cached_input_tokens', 0) or 0); tout += u.get('output_tokens', 0) or 0; turns += 1
    if text is None: raise json.JSONDecodeError('no agent_message event in the codex stream', stdout[:200], 0)
    return text, {'cost_usd': 0, 'tokens_in': tin, 'tokens_out': tout, 'turns': turns or None}


def model_call(prompt, workdir, model=None, host=None):
    """One model call confined to workdir (read-only tools). claude profile: prompt after -p, tools restricted to Read/Grep/Glob;
    openai profile: prompt on stdin (codex `-`), --json event stream parsed. Returns (text, measure) or (None, {'error': ...})."""
    host = host_name(host)
    env = {k: v for k, v in os.environ.items() if k not in ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN')}
    model = default_model(host) if model is None else model
    argv = strip_model([a.replace('{model}', model) for a in model_command(host)])
    stdin = None
    if host == 'claude':
        if '-p' in argv: argv.insert(argv.index('-p') + 1, prompt)
        else: argv += ['-p', prompt]
        argv += ['--allowedTools', TOOLS_OK, '--disallowedTools', TOOLS_NO]
    else:
        stdin = prompt
    t0 = time.time()
    try:
        io = {'input': stdin} if stdin is not None else {'stdin': subprocess.DEVNULL}
        r = subprocess.run(argv, cwd=workdir, env=env, capture_output=True, text=True, timeout=TIMEOUT, **io)
        text, m = _parse_claude(r.stdout) if host == 'claude' else _parse_codex(r.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        return None, {'error': str(e)[:300], 'seconds': round(time.time() - t0, 1), 'cost_usd': 0, 'host': host}
    return text, {'seconds': round(time.time() - t0, 1), 'host': host, **m}


def key_of(claim, card):
    s = claim.get('source') or {}
    if s.get('key'): return s['key']
    for k, v in (card.get('sources') or {}).items():        # find the key through an identifier
        if any(s.get(x) and s.get(x) == v.get(x) for x in ('doi', 'arxiv', 'pmid', 'pmcid')): return k
    return next((f'{x}:{s[x]}' for x in ('doi', 'arxiv', 'pmid', 'pmcid') if s.get(x)), None)


def fs_key(c):
    """File-system-safe name for a source key or a card id (a key may be an identifier such as doi:10.1/x, a card id comes from
    a model-written card): never a separator, never '..', never empty."""
    s = re.sub(r'[^\w.-]+', '_', str(c or '')).strip('.')
    return s or 'source'


def ident_of(desc):
    """{doi|arxiv|pmid|pmcid} -> gateway identifier (pmcid is not read by the gateway: None)."""
    for x in ('doi', 'arxiv', 'pmid'):
        if desc.get(x): return f'{x}:{desc[x]}'
    return None


def load_sources(card, sources_dir=None, gateway=None, fulltext=False, out_dir=None):
    """-> {key: {'text': str, 'origin': 'fulltext|abstract|missing', 'note': str, 'desc': dict}} for each key cited by the card."""
    keys = sorted({c for c in (key_of(a, card) for a in card['claims']) if c})
    table = card.get('sources') or {}
    out = {}
    for c in keys:
        desc = table.get(c) or {}
        txt = None; origin = 'missing'; note = ''
        if sources_dir:                                      # sources/<key>/source.txt (layout written by --fulltext) or sources/<key>.txt
            for f in (pathlib.Path(sources_dir) / fs_key(c) / 'source.txt', pathlib.Path(sources_dir) / (fs_key(c) + '.txt')):
                if f.is_file(): txt = f.read_text(errors='replace'); origin = 'fulltext'; break
        if txt is None and fulltext and out_dir and any(desc.get(x) for x in ('arxiv', 'doi', 'pmcid')):
            d = pathlib.Path(out_dir) / fs_key(c); d.mkdir(parents=True, exist_ok=True)
            arg = next(f'--{x}' for x in ('arxiv', 'doi', 'pmcid') if desc.get(x))
            subprocess.run([sys.executable, '-I', str(ROLE_DIR / 'fetch_fulltext.py'), arg, desc[arg[2:]], '--out', str(d)], capture_output=True, timeout=600)
            if (d / 'source.txt').exists() and (d / 'source.txt').stat().st_size > 0:
                txt = (d / 'source.txt').read_text(errors='replace'); origin = 'fulltext'
        if txt is None and gateway is not None:
            ident = ident_of(desc) or (c if re.match(r'^(doi|arxiv|pmid):', c) else None)
            if ident:
                rep = gateway.read(ident) or {}
                r = rep.get('results') or {}
                if isinstance(r, dict) and r.get('abstract') and not NO_ABSTRACT.match(str(r['abstract'])):
                    txt = f"{r.get('title') or ''}\n\n{r['abstract']}"; origin = 'abstract'; note = '(record + abstract)'
                else: note = rep.get('refusal') or rep.get('error') or (r.get('refusal') or r.get('error') if isinstance(r, dict) else None) or 'no abstract'
        if txt is not None and not txt.strip(): txt = None; origin = 'missing'
        out[c] = {'text': txt or '', 'origin': origin, 'note': note, 'desc': desc}
    return out


def prepare(workdir, card, sources):
    workdir = pathlib.Path(workdir)
    if workdir.exists(): shutil.rmtree(workdir)                # throwaway working directory, created by this wrapper
    (workdir / 'sources').mkdir(parents=True)
    shutil.copy(ROLE_FILE, workdir / 'ROLE.md')
    f = dict(card); f['sources'] = {fs_key(c): {**(s.get('desc') or {}), 'note': s['note']} for c, s in sources.items() if s['origin'] != 'missing'}
    f['claims'] = [dict(a, source=dict(a.get('source') or {}, key=fs_key(key_of(a, card)))) for a in card['claims']
                   if sources.get(key_of(a, card), {}).get('origin') != 'missing']   # the reader sees file-system-safe keys only
    (workdir / 'card.json').write_text(json.dumps(f, ensure_ascii=False, indent=1))
    texts = {}
    for c, s in sources.items():
        if s['origin'] == 'missing': continue
        (workdir / 'sources' / fs_key(c)).mkdir(exist_ok=True)
        (workdir / 'sources' / fs_key(c) / 'source.txt').write_text(s['text'])
        texts[c] = norm(s['text'])
    return texts, any(s['origin'] == 'abstract' for s in sources.values())


def _unit(card, sources, engine, workdir):
    """One call + a single retry; verdicts by id, after the mechanical check of the fragments (INVALID if the failure persists)."""
    texts, abstract = prepare(workdir, card, sources)
    expected = [a['id'] for a in card['claims'] if sources.get(key_of(a, card), {}).get('origin') != 'missing']
    prompt = PROMPT + (ABSTRACT_NOTE if abstract else '')
    measures, verdicts = [], {}
    if expected:
        txt, m = engine(prompt, str(workdir)); measures.append(m)
        verdicts = {v.get('id'): v for v in (extract_json(txt) or {}).get('verdicts', []) if v.get('id') in expected}
    pbs = check(list(verdicts.values()), texts)
    missing = [i for i in expected if i not in verdicts]
    retry = bool(pbs or missing) and bool(measures) and 'error' not in measures[0]
    if retry:
        faulty = sorted(set(pbs) | set(missing))
        details = '\n'.join(f'- {i}: ' + '; '.join(pbs.get(i, ['missing verdict or unreadable JSON'])) for i in faulty)
        p2 = (prompt + f'\n\nRETRY: the following verdicts were rejected by the mechanical check of the fragments:\n{details}\n'
              f'Redo ONLY these claims ({", ".join(faulty)}): copy the fragments character for character '
              'from the output of Grep. Same JSON format.')
        txt2, m2 = engine(p2, str(workdir)); measures.append(m2)
        for v in (extract_json(txt2) or {}).get('verdicts', []):
            if v.get('id') in faulty: verdicts[v['id']] = v
        pbs = check([verdicts[i] for i in expected if i in verdicts], texts)
    failed = bool(measures) and 'error' in measures[0] and len(measures) == 1
    out = {}
    for i in expected:
        v = verdicts.get(i)
        if v is None:
            out[i] = {'status': 'UNVERIFIED', 'discrepancy': measures[0].get('error', 'no verdict') if failed else 'no verdict returned'}
            continue
        status = (v.get('verdict') or '').upper()
        if i in pbs: status, v = 'INVALID', dict(v, problems=pbs[i])
        if status not in STATUSES: status, v = 'INVALID', dict(v, problems=[f'unknown verdict: {v.get("verdict")!r}'])
        out[i] = {'status': status, 'discrepancy': v.get('discrepancy', ''), 'fragments': v.get('fragments', []), 'location': v.get('location', ''),
                  'confidence': v.get('confidence', ''), 'elements': v.get('elements', []), **({'problems': v['problems']} if 'problems' in v else {})}
    return out, measures, retry


def verify(card, sources, engine, work=None, mode='auto', max_chars=MAX_CHARS):
    """card (dict) + sources ({key: {'text','origin','note'}}, see load_sources) + engine -> report of the statuses.
    mode auto: one call per card (measured 81/81, -32 % cost), split per source when the sources exceed max_chars."""
    work = pathlib.Path(work or tempfile.mkdtemp(prefix='vp-verify-'))
    size = sum(len(s['text']) for s in sources.values())
    per_source = mode == 'source' or (mode == 'auto' and size > max_chars)
    verdicts, measures, retries = {}, [], 0
    if per_source:
        for c in sorted(sources):
            sub = dict(card, claims=[a for a in card['claims'] if key_of(a, card) == c])
            if not sub['claims']: continue
            v, m, r = _unit(sub, {c: sources[c]}, engine, work / fs_key(f'{card["card_id"]}-{c}'))
            verdicts.update(v); measures += m; retries += r
    else:
        verdicts, measures, r = _unit(card, sources, engine, work / fs_key(card['card_id'])); retries = int(r)
    claims = []
    for a in card['claims']:
        c = key_of(a, card); s = sources.get(c, {})
        base = {'id': a['id'], 'text': a['text'], 'source': c, 'source_origin': s.get('origin', 'missing')}
        if s.get('origin', 'missing') == 'missing':
            claims.append({**base, 'status': 'SOURCE-UNAVAILABLE', 'discrepancy': s.get('note') or 'source not provided'})
        else:
            claims.append({**base, **verdicts.get(a['id'], {'status': 'UNVERIFIED', 'discrepancy': 'no verdict'})})
    summary = {s: sum(a['status'] == s for a in claims) for s in STATUSES}
    verifiable = sum(summary[s] for s in ('FOUND', 'DISTORTED', 'ABSENT', 'INVALID'))
    summary['unsupported_rate'] = round(sum(summary[s] for s in UNSUPPORTED) / verifiable, 3) if verifiable else None
    return {'card_id': card['card_id'], 'question': card.get('question', ''), 'mode': 'source' if per_source else 'card',
            'role_file': 'tools/verifier/ROLE.md', 'claims': claims, 'summary': summary, 'retries': retries, 'measures': measures,
            'cost_usd': round(sum(m.get('cost_usd', 0) or 0 for m in measures), 4), 'seconds': round(sum(m.get('seconds', 0) or 0 for m in measures), 1)}


def filter_claims(report):
    """Downstream rule: keep FOUND and SOURCE-UNAVAILABLE (flagged); remove DISTORTED, ABSENT, INVALID; UNVERIFIED kept and flagged."""
    kept = [a for a in report['claims'] if a['status'] not in UNSUPPORTED]
    removed = [a for a in report['claims'] if a['status'] in UNSUPPORTED]
    return {'kept': kept, 'removed': removed, 'to_flag': [a for a in kept if a['status'] != 'FOUND']}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='action', required=True)
    v = sub.add_parser('verify')
    v.add_argument('--card', required=True); v.add_argument('--sources', default=None); v.add_argument('--out', required=True)
    v.add_argument('--T', default=None); v.add_argument('--plugin', action='append', default=[]); v.add_argument('--run', default='verify')
    v.add_argument('--state', default=None); v.add_argument('--fulltext', action='store_true')
    v.add_argument('--model', default=None, help='default: VP_MODEL, else tools/config.json verifier.model[host], else the host CLI default')
    v.add_argument('--host', choices=['claude', 'openai'], default=None)
    v.add_argument('--mode', choices=['auto', 'card', 'source'], default='auto'); v.add_argument('--work', default=None)
    v.add_argument('--filter', action='store_true', help='adds kept/removed according to the downstream rule')
    c = sub.add_parser('check'); c.add_argument('verdicts'); c.add_argument('sources_dir')
    a = ap.parse_args()
    if a.action == 'check':
        p = check(json.loads(pathlib.Path(a.verdicts).read_text(encoding='utf-8'))['verdicts'], load_texts(a.sources_dir))
        print(json.dumps(p, ensure_ascii=False, indent=1)); sys.exit(1 if p else 0)
    card = json.loads(pathlib.Path(a.card).read_text(encoding='utf-8'))
    gateway = None
    if a.T or a.plugin:
        sys.path.insert(0, str(HERE)); from gateway import Gateway
        gateway = Gateway(a.plugin, T=a.T, run=a.run, state=a.state)
    sources = load_sources(card, a.sources, gateway, a.fulltext, out_dir=a.sources or (a.work and pathlib.Path(a.work) / 'sources'))
    engine = lambda prompt, workdir: model_call(prompt, workdir, a.model, a.host)
    res = verify(card, sources, engine, a.work, a.mode)
    if a.filter: res['filter'] = filter_claims(res)
    pathlib.Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(res['summary'], ensure_ascii=False))


if __name__ == '__main__':
    main()
