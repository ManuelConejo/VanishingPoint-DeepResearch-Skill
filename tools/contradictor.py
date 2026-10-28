#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Contradictor after the report (plugins/code.md, section "Contradictor after the report"; SKILL.md, "Contradictor"). Optional.

One contradictor per configured model family reads REPORT.md, the condensed Y and the whole files of X that whole_reading.py
built (state/whole-reading/material-Y.txt, cut at the contradictor cap at a file boundary, and material-X.txt), with no tool, and
returns at most 3 statements of the report it judges FALSE (exact quotation + evidence references) and at most 3 composite
capabilities or concrete defects of X the report MISSED (references on both sides), as strict JSON (prompts/CONTRADICTOR.md).
Nothing is taken on the contradictor's word:
  (a) mechanical check: the quotation is found in REPORT.md (normalised substring, else difflib ratio >= 0.85 on a sliding
      window); every reference names a file and a line that exist in the material; a miss needs a reference on both sides;
  (b) a miss already stated in the report is dropped: one fresh-context call on the host model (prompts/CONTRADICTOR-MATCH.md),
      list A = the findings of the report, list B = the candidate misses of every family mixed;
  (c) one fresh-context reread per surviving element on the host model, with the cited extracts only: a false claim
      (prompts/CONTRADICTOR-REREAD-FALSE.md) -> CONTRADICTED / NOT CONTRADICTED; a miss (prompts/CONTRADICTOR-REREAD-MISS.md,
      X-side extracts) -> FOUND / ABSENT.
Output: <run>/contradictor.json (every element with its final status, the costs, the material used) and one JSON status line on
stdout telling the orchestrator what to apply: "false detected" -> annotate the finding "contradicted by <family>: <why>" and
keep the quotation out of the executive summary and verdicts; "miss verified" -> add the finding (its references go through the
verifier, SKILL.md section 7, like any other); everything else stays in contradictor.json. The methodology appendix states the
families, the counts and the cost. The tool never edits REPORT.md.

Families: --families, else VP_CONTRADICTORS (comma-separated), else ~/.config/vp/contradictors (comma- or line-separated),
else tools/config.json "contradictor.families" (empty by default: the option is absent, the tool prints {"status": "absent"}).
A family is written <via>[:<model>], and no model name is fixed in the code or the config:
  openai[:<model>]      the Codex CLI through the `openai` host profile of model_command (read-only sandbox, empty directory);
  claude[:<model>]      `claude -p` without tool through the `claude` host profile;
  <provider>:<model>    any OpenAI-compatible chat-completions API named in tools/config.json "contradictor.providers" (openrouter,
                        gemini, openai-api, mistral, ollama, or one you add there or in VP_CONTRADICTOR_PROVIDERS as JSON): url, key =
                        the name of its key variable (resolved as in KEYS.md: environment, then ~/.config/vp/<name>.key; null = no key),
                        extra = fields merged into the request body. VP_CONTRADICTOR_URL_<PROVIDER> overrides a url (tests).
For a CLI, an empty model = the CLI's own default model, so the choice follows the vendor; for an API the model id is required.
The receipt records the model actually used. A family whose key, url or command is missing is skipped with the reason
(credential_missing, provider_unknown, command_missing), never silently. A contradictor of the same family as the author of the
report is allowed but defeats the purpose: the receipt says which family wrote each element. The natural choice: the other CLI
(openai on a Claude Code host, claude on a Codex host), or any API of another vendor.
Measured on 2026-10-27 (6 code cases): openai (gpt-5.6-sol), openrouter:moonshotai/kimi-k3.1-pro, openrouter:google/gemini-4-argon;
see CHANGELOG.md.
Rereads and the match call: host profile --host / VP_HOST / config "host"; model --model / VP_MODEL / config
"contradictor.reread_model"[host]. VP_OPENROUTER_URL overrides the OpenRouter endpoint (tests). No key value is ever printed
or written. No clone, no execution: the tool reads the run directory only.

Usage: contradictor.py RUN_DIR [--families F ...] [--host claude|openai] [--model M] [--y-cap N] [--max-usd U] [--prompts-only]
"""
import argparse, datetime as dt, difflib, hashlib, json, os, pathlib, re, shutil, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request
from types import SimpleNamespace

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); import whole_reading as W, code_sources as sc  # noqa: E402  (python3 -I does not add the script directory)
CFG = json.loads((HERE / 'config.json').read_text())
CO = CFG.get('contradictor', {})
Y_CAP = int(CO.get('y_cap_chars', 220000)); MAX_USD = float(CO.get('max_usd', 4.0)); REREAD_USD = float(CO.get('reread_usd_per_call', 0.4))
TIMEOUT = int(CO.get('timeout_s', 900)); MAX_PER_LIST = int(CO.get('max_per_list', 3))
REQUEST = CO.get('request') or {'temperature': 0, 'max_tokens': 8000}
BLOCK = re.compile(r'^=== (.+?) @([0-9a-f]{7,40}) \((\d+) lines\) ===$', re.M)
BLOCK_PAPER = re.compile(r'^=== (arxiv:[\w.]+) \((\d+) lines\) ===$', re.M)
PAPER_REF = re.compile(r'(?i)(arxiv:\s*\d{4}\.\d{4,5}(?:v\d+)?)\s*[,:(]?\s*(?:lines?|l\.|ll\.)?\s*(\d+)(?:\s*[-–]\s*(\d+))?')
LINE = re.compile(r'^(\d+)\t')


def utc(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def chown(p):
    uid, gid = CFG.get('chown', [None, None]) if isinstance(CFG.get('chown'), list) else (None, None)
    if uid is None: return
    for q in [p] + list(p.rglob('*')):
        try: os.chown(q, uid, gid)
        except OSError: pass


# ------------------------------------------------------------------ configuration
def families(arg=None):
    """Names only, in order, without duplicates: --families, else VP_CONTRADICTORS, else ~/.config/vp/contradictors, else config."""
    raw = list(arg) if arg else None
    if raw is None and os.environ.get('VP_CONTRADICTORS', '').strip(): raw = [os.environ['VP_CONTRADICTORS']]
    if raw is None:
        try: raw = [(pathlib.Path.home() / '.config' / 'vp' / 'contradictors').read_text(encoding='utf-8')]
        except OSError: raw = None
        if raw is not None and not ''.join(l.split('#', 1)[0] for l in raw[0].splitlines()).strip(): raw = None   # blank file = absent, as check_keys
    if raw is None: raw = [str(x) for x in (CO.get('families') or [])]
    out = []
    for chunk in raw:
        for line in chunk.splitlines() or ['']:
            for name in re.split(r'[,\s]+', line.split('#', 1)[0].strip()):
                name = name.strip().lower()
                if name and name not in out: out.append(name)
    return out


def fname(name): return re.sub(r'[^\w.-]+', '_', name)


def providers():
    """OpenAI-compatible endpoints: tools/config.json contradictor.providers, overridden or extended by VP_CONTRADICTOR_PROVIDERS (JSON)."""
    out = {k.lower(): v for k, v in (CO.get('providers') or {}).items() if isinstance(v, dict)}
    raw = os.environ.get('VP_CONTRADICTOR_PROVIDERS', '').strip()
    if raw:
        try: out.update({k.lower(): v for k, v in json.loads(raw).items() if isinstance(v, dict)})
        except (ValueError, AttributeError): pass
    return out


def family_spec(name):
    """<via>[:<model>] -> {'via', 'model', 'kind': 'cli'|'http', 'provider'}; '' model = the host CLI's default; None when unknown."""
    via, _, model = name.partition(':'); via = via.strip().lower(); model = model.strip()
    if via in ('openai', 'claude'): return dict(via=via, model=model, kind='cli')
    prov = providers().get(via)
    if prov and model: return dict(via=via, model=model, kind='http', provider=prov)
    return None


def host_name(a): return a.host or os.environ.get('VP_HOST') or CFG.get('host', 'claude')


def reread_model(a, host):
    """--model, else VP_MODEL, else config contradictor.reread_model[host]; '' = the host CLI's default model."""
    m = CO.get('reread_model')
    return a.model or os.environ.get('VP_MODEL') or (m.get(host, '') if isinstance(m, dict) else (m or '')) or ''


def strip_model(argv):
    """Without a model name, the host CLI decides: drop `--model ''` / `-m ''` left by the template."""
    out = []; skip = False
    for i, x in enumerate(argv):
        if skip: skip = False; continue
        if x in ('--model', '-m') and i + 1 < len(argv) and argv[i + 1] == '': skip = True; continue
        out.append(x)
    return out


# ------------------------------------------------------------------ material (built by whole_reading.py, read here)
def parse_material(text):
    """Blocks of a material text -> {path: dict(sha, n, lines, kind)}; the paper form `=== arxiv:ID (N lines) ===` has sha ''."""
    out = {}; lines = text.splitlines(); i = 0
    while i < len(lines):
        m = BLOCK.match(lines[i]); mp = BLOCK_PAPER.match(lines[i]) if not m else None
        if not m and not mp: i += 1; continue
        path, sha, n = (m.group(1), m.group(2), int(m.group(3))) if m else (mp.group(1), '', int(mp.group(2)))
        body = []; i += 1
        while i < len(lines) and LINE.match(lines[i]): body.append(lines[i].split('\t', 1)[1] if '\t' in lines[i] else ''); i += 1
        out[path] = dict(sha=sha, n=n, lines=body, kind='paper' if mp else 'file')
    return out


def truncate_y(text, cap):
    """Cut Y at the last file boundary under cap; declare the files listed but not included. Returns (text, excluded paths)."""
    if len(text) <= cap: return text, []
    starts = [m.start() for m in BLOCK.finditer(text)] + [m.start() for m in BLOCK_PAPER.finditer(text)]
    starts.sort(); cut = max([s for s in starts if s <= cap] or [cap])
    kept, rest = text[:cut].rstrip() + '\n', text[cut:]
    excluded = [m.group(1) for m in BLOCK.finditer(rest)] + [m.group(1) for m in BLOCK_PAPER.finditer(rest)]
    head = (f"# [Contradictor: Y cut at {cap} characters at the last file boundary; {len(excluded)} files listed in the tree but NOT INCLUDED "
            f"(contradictor cap): " + ', '.join(excluded[:200]) + (' ...' if len(excluded) > 200 else '') + "]\n\n")
    return head + kept, excluded


def resolve(path, blocks):
    """Exact path, else unique suffix match (a/b/c.py matches b/c.py or c.py)."""
    if path in blocks: return path
    hits = [p for p in blocks if p.endswith('/' + path) or path.endswith('/' + p)]
    return hits[0] if len(hits) == 1 else None


def parse_refs(strings, xb, yb):
    """References of the contradictor -> [{ref, side, path, l1, l2, sha, exists, note}]; side in X, Y, unknown."""
    out = []; seen = set()
    for s in (strings if isinstance(strings, list) else [strings]):
        s = str(s)
        for m in W.REF.finditer(s):
            path, l1, l2, sha = m.group(1), int(m.group(2)), int(m.group(3) or m.group(2)), m.group(4)
            r = dict(ref=m.group(0), path=path, l1=l1, l2=max(l1, l2), sha=sha, side='unknown', exists=False, note='')
            for side, blocks in (('X', xb), ('Y', yb)):
                p = resolve(path, blocks)
                if p and (blocks[p]['sha'].startswith(sha) or sha.startswith(blocks[p]['sha'])):
                    r.update(side=side, path=p, exists=r['l2'] <= blocks[p]['n'], note=f"{blocks[p]['n']} lines" if r['l2'] <= blocks[p]['n'] else f"line beyond the file ({blocks[p]['n']} lines)"); break
            else: r['note'] = 'not in the material (file or SHA)'
            if r['ref'] not in seen: seen.add(r['ref']); out.append(r)
        for m in PAPER_REF.finditer(s):
            ident = re.sub(r'\s+', '', m.group(1)).lower(); l1 = int(m.group(2)); l2 = int(m.group(3) or l1)
            r = dict(ref=m.group(0), path=ident, l1=l1, l2=max(l1, l2), sha='', side='unknown', exists=False, note='')
            p = next((k for k in yb if k.lower() == ident), None)
            if p: r.update(side='Y', path=p, exists=r['l2'] <= yb[p]['n'], note=f"{yb[p]['n']} lines" if r['l2'] <= yb[p]['n'] else 'line beyond the text')
            else: r['note'] = 'paper not in the material'
            if r['ref'] not in seen: seen.add(r['ref']); out.append(r)
    return out


def extracts(refs, xb, yb, window=40, whole_below=400):
    """Windows of the material for existing references: the whole block when it has <= 400 lines, else +-40 lines."""
    blocks = []
    for r in refs:
        if not r['exists']: continue
        b = (xb if r['side'] == 'X' else yb)[r['path']]; n = len(b['lines'])
        a, z = (1, n) if n <= whole_below else (max(1, r['l1'] - window), min(n, r['l2'] + window))
        tag = f"@{b['sha'][:12]}" if b['sha'] else ''
        blocks.append(f"=== {r['path']} {tag} (lines {a}-{z} of {n}) ===\n" + '\n'.join(f'{i}\t{b["lines"][i - 1]}' for i in range(a, z + 1)))
    return '\n\n'.join(blocks) or '(no readable extract)'


# ------------------------------------------------------------------ quotations in the report
def normalise(s):
    s = re.sub(r'[«»“”„"]', '"', s); s = re.sub(r"[‘’`]", "'", s); return re.sub(r'\s+', ' ', s).strip().lower().strip(' ."\'')


def norm_map(text):
    """Normalised text plus, for each normalised character, its offset in the original (to cut a context in the original)."""
    out = []; idx = []; prev_space = False
    for i, ch in enumerate(text):
        c = '"' if ch in '«»“”„' else "'" if ch in '‘’`' else ch
        if c.isspace():
            if prev_space or not out: continue
            out.append(' '); idx.append(i); prev_space = True
        else: out.append(c.lower()); idx.append(i); prev_space = False
    return ''.join(out), idx


def find_quote(quote, report):
    """(found, position in the original report, method): substring of the normalised text, else difflib ratio >= 0.85 on a sliding window."""
    q = normalise(quote); r, idx = norm_map(report)
    if not q: return False, -1, 'empty'
    k = r.find(q)
    if k >= 0: return True, idx[k], 'substring'
    if len(q) < 12 or len(r) < len(q): return False, -1, 'not found'
    best, where = 0.0, -1; step = max(1, len(q) // 4)
    for s in range(0, len(r) - len(q) + 1, step):
        m = difflib.SequenceMatcher(None, q, r[s:s + len(q)], autojunk=False)
        if m.real_quick_ratio() < 0.85 or m.quick_ratio() < 0.85: continue
        ratio = m.ratio()
        if ratio > best: best, where = ratio, s
    return (True, idx[where], f'difflib {best:.2f}') if best >= 0.85 else (False, -1, 'not found')


def context(report, pos, margin=600):
    return report[max(0, pos - margin):pos + margin]


def findings(report):
    """List A for the match call: the `### Finding` paragraphs of the report (heading + 500 characters), else the report itself."""
    parts = re.split(r'^(?=### )', report, flags=re.M)
    items = [p.strip() for p in parts if p.startswith('### ')]
    if not items: items = [report.strip()[:40000]]
    return [i[:500] for i in items]


# ------------------------------------------------------------------ model calls
def extract_json(txt):
    t = (txt or '').strip()
    t = re.sub(r'^```(?:json)?\s*|\s*```$', '', t)
    a, z = t.find('{'), t.rfind('}')
    if a < 0 or z <= a: return None
    try: j = json.loads(t[a:z + 1])
    except ValueError: return None
    return j if isinstance(j, dict) else None


def http_call(spec, prompt, trace):
    """One chat-completions call to an OpenAI-compatible endpoint (fields of config "request" plus the provider's "extra").
    Returns (text, measure); the key goes in the Authorization header only and is never written anywhere."""
    prov = spec['provider']; name = spec['via']
    url = os.environ.get('VP_CONTRADICTOR_URL_' + re.sub(r'\W', '_', name).upper()) or prov.get('url')
    if not url: return None, dict(error='provider_unknown', usd=0.0, note=f'provider {name}: no url (tools/config.json contradictor.providers)')
    keyvar = prov.get('key'); key = sc.key(keyvar) if keyvar else None
    if keyvar and not key: return None, dict(error='credential_missing', usd=0.0, note=f'{keyvar} absent (environment or ~/.config/vp/{keyvar.lower()}.key; KEYS.md)')
    host = urllib.parse.urlsplit(url).hostname or ''
    if key and not url.startswith('https://') and host not in ('localhost', '127.0.0.1', '::1'):
        return None, dict(error='insecure_url', usd=0.0, note=f'provider {name}: a key is only sent over https (or to localhost)')
    body = {'model': spec['model'], 'messages': [{'role': 'user', 'content': prompt}], **REQUEST, **(prov.get('extra') or {})}
    headers = {'Content-Type': 'application/json', 'X-Title': 'vanishingpoint-contradictor', **(prov.get('headers') or {})}
    if key: headers['Authorization'] = 'Bearer ' + key
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    t0 = time.monotonic()
    try:
        with urllib.request.build_opener(sc._NoRedirect()).open(req, timeout=TIMEOUT) as r: rep = json.load(r)   # never follow a redirect with the key
    except urllib.error.HTTPError as e: return None, dict(error=f'HTTP {e.code}', detail=e.read().decode('utf-8', 'replace')[:300], usd=0.0, seconds=round(time.monotonic() - t0))
    except (urllib.error.URLError, OSError, ValueError) as e: return None, dict(error=str(e)[:300], usd=0.0, seconds=round(time.monotonic() - t0))
    content = ((rep.get('choices') or [{}])[0].get('message') or {}).get('content') or ''; u = rep.get('usage') or {}
    txt = content if isinstance(content, str) else ''.join(p.get('text', '') if isinstance(p, dict) else str(p) for p in content)   # list of parts on some gateways
    trace.write_text(json.dumps(dict(utc=utc(), provider=name, model=spec['model'], usage=u, chars=len(txt)), ensure_ascii=False) + '\n')
    cost = u.get('cost')
    return txt, dict(usd=float(cost) if cost is not None else 0.0, cost_known=cost is not None, tokens_in=u.get('prompt_tokens'), tokens_out=u.get('completion_tokens'), seconds=round(time.monotonic() - t0))


def host_call(host, model, prompt, trace, usd_cap=REREAD_USD):
    """One fresh-context call on the host profile (claude -p without tool, or codex exec read-only), prompt on stdin, in an empty directory."""
    try: argv = strip_model(W.command(host, model))
    except (KeyError, ValueError) as e: return None, dict(error=f'command_missing: {e}', usd=0.0)
    if host == 'claude' and '--max-budget-usd' in argv: argv[argv.index('--max-budget-usd') + 1] = str(usd_cap)
    if not (os.path.isabs(argv[0]) and os.access(argv[0], os.X_OK)) and not shutil.which(argv[0]): return None, dict(error=f'command_missing: {argv[0]}', usd=0.0)
    env = {k: v for k, v in os.environ.items() if k not in ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN')}
    env['CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS'] = '0'
    cwd = tempfile.mkdtemp(prefix='vp-contradictor-'); t0 = time.monotonic()
    with open(trace, 'w') as out, open(str(trace) + '.err', 'w') as err:
        try: rc = subprocess.run(argv, cwd=cwd, input=prompt.encode(), stdout=out, stderr=err, env=env, timeout=TIMEOUT).returncode
        except subprocess.TimeoutExpired: rc = -9
        except OSError as e: rc = -1; err.write(str(e))
    shutil.rmtree(cwd, ignore_errors=True)
    txt, m = (W.parse_claude if host == 'claude' else W.parse_openai)(trace)
    m = dict(m, rc=rc, seconds=round(time.monotonic() - t0), usd=float(m.get('usd') or 0))
    if not txt: m['error'] = m.get('error') or f'empty answer (rc {rc})'
    return (txt or None), m


def contradictor_call(spec, prompt, d, name):
    if spec['kind'] == 'http': return http_call(spec, prompt, d / f'{fname(name)}.trace.jsonl')
    return host_call(spec['via'], spec['model'], prompt, d / f'{fname(name)}.trace.jsonl', usd_cap=MAX_USD)


# ------------------------------------------------------------------ the run
def build_prompt(a, report, y, x, xb, yb):
    g = (HERE / 'prompts' / 'CONTRADICTOR.md').read_text()
    y_shas = sorted({b['sha'][:12] for b in yb.values() if b['sha']}); x_shas = sorted({b['sha'][:12] for b in xb.values() if b['sha']})
    y_form = f"<path>:<line>@{' or @'.join(y_shas)}" if y_shas else ('arxiv:<id> (line N)' if any(b['kind'] == 'paper' for b in yb.values()) else '<path>:<line>@<SHA of Y>')
    x_sha = ' or '.join(x_shas) or '<SHA of X>'
    return W.fill(g, {'T': a.T, 'REQUEST': a.request, 'TARGET': a.target, 'Y_FORM': y_form, 'X_SHA': x_sha,
                      'REPORT': report.rstrip(), 'Y': y.rstrip(), 'X': x.rstrip()})


def as_list(v):
    """A list from the contradictor's JSON field: a dict or a string becomes a one-element list, anything else empty."""
    return v if isinstance(v, list) else [v] if isinstance(v, (dict, str)) and v else []


def analyse(name, j, report, xb, yb):
    """Mechanical check of one family's JSON -> elements with a status ('to reread', 'to match', or a final 'false added ...' / 'miss false ...')."""
    els = []
    for i, f in enumerate(as_list(j.get('false_claims'))[:MAX_PER_LIST]):
        if not isinstance(f, dict): f = {'quote': str(f)}
        quote = str(f.get('quote') or ''); ev = f.get('evidence') or []; why = str(f.get('why') or '')
        found, pos, method = find_quote(quote, report); refs = parse_refs(ev if isinstance(ev, list) else [str(ev)], xb, yb)
        refs_ok = bool(refs) and all(r['exists'] for r in refs)
        status = ('to reread' if found and refs_ok else 'false added: quotation not found in the report' if not found
                  else 'false added: no reference' if not refs else 'false added: reference missing from the material')
        els.append(dict(kind='false', family=name, i=i + 1, quote=quote[:600], evidence=[str(e)[:200] for e in (ev if isinstance(ev, list) else [ev])], why=why[:800],
                        quote_found=found, quote_method=method, position=pos, refs=refs, status=status))
    for i, m in enumerate(as_list(j.get('missed'))[:MAX_PER_LIST]):
        if not isinstance(m, dict): m = {'claim': str(m)}
        claim = str(m.get('claim') or ''); ry = m.get('refs_Y') or []; rx = m.get('refs_X') or []; why = str(m.get('why') or '')
        ry = [str(v) for v in (ry if isinstance(ry, list) else [ry])]; rx = [str(v) for v in (rx if isinstance(rx, list) else [rx])]
        refs = parse_refs(ry + rx, xb, yb)
        has_x = any(r['side'] == 'X' and r['exists'] for r in refs); has_y = any(r['side'] == 'Y' and r['exists'] for r in refs)
        ok = bool(refs) and all(r['exists'] for r in refs) and has_x and has_y
        status = ('to match' if ok else 'miss false: no reference' if not refs else 'miss false: reference missing from the material' if not all(r['exists'] for r in refs)
                  else 'miss false: X side absent' if not has_x else 'miss false: Y side absent')
        els.append(dict(kind='miss', family=name, i=i + 1, claim=claim[:800], refs_Y=[v[:200] for v in ry], refs_X=[v[:200] for v in rx], why=why[:800], refs=refs, status=status))
    return els


def match(els, report, host, model, d, costs):
    """One call: which candidate misses are already stated by the report (same mechanism for the same purpose)? Strict rule: matched = not exclusive."""
    cands = [e for e in els if e['status'] == 'to match']
    if not cands: return
    g = (HERE / 'prompts' / 'CONTRADICTOR-MATCH.md').read_text()
    la = '\n\n'.join(f'### A{i + 1}\n{t}' for i, t in enumerate(findings(report)))
    lb = '\n\n'.join(f"### B{i + 1}\n{e['claim']}\n  why: {e['why']}\n  Y side: {', '.join(e['refs_Y'])}\n  X side: {', '.join(e['refs_X'])}" for i, e in enumerate(cands))
    if costs['rereads'] + REREAD_USD > MAX_USD:
        for e in cands: e['status'] = 'not reread: contradictor budget reached'
        return
    p = W.fill(g, {'LIST_A': la, 'LIST_B': lb})
    txt, m = host_call(host, model, p, d / 'match.trace.jsonl'); costs['rereads'] += m.get('usd') or 0
    j = extract_json(txt or '')
    if j is None:
        for e in cands: e['status'] = 'not reread: match call failed'; e['match'] = m.get('error') or 'no JSON'
        return
    matched = set()
    for pair in (j.get('pairs') or []):
        if isinstance(pair, dict) and str(pair.get('B', '')).upper().startswith('B'):
            try: matched.add(int(str(pair['B'])[1:]))
            except ValueError: pass
    for i, e in enumerate(cands):
        e['exclusive'] = (i + 1) not in matched; e['status'] = 'to reread' if e['exclusive'] else 'not exclusive: already stated in the report'


def first_verdict(up, words):
    """The verdict word at the start of the answer, as a whole word (UNCONTRADICTED or UNFOUNDED never count); else UNDECIDED."""
    line = next((l.strip(' *`."\'') for l in up.splitlines() if l.strip()), '')
    for w in words:
        if re.match(r'^' + re.escape(w) + r'\b', line): return w
    return 'UNDECIDED'


def reread(els, report, xb, yb, host, model, d, costs):
    n = 0
    for e in els:
        if e['status'] != 'to reread': continue
        if costs['rereads'] + REREAD_USD > MAX_USD: e['status'] = 'not reread: contradictor budget reached'; continue
        n += 1; trace = d / f"reread-{n}-{e['kind']}-{fname(e['family'])}-{e['i']}.trace.jsonl"
        if e['kind'] == 'false':
            g = (HERE / 'prompts' / 'CONTRADICTOR-REREAD-FALSE.md').read_text()
            p = W.fill(g, {'QUOTATION': e['quote'], 'CONTEXT': context(report, e['position']),
                           'OBJECTION': e['why'] + '\nReferences: ' + ', '.join(e['evidence']), 'EXTRACTS': extracts(e['refs'], xb, yb)})
            txt, m = host_call(host, model, p, trace); costs['rereads'] += m.get('usd') or 0; up = (txt or '').upper()
            verdict = first_verdict(up, ('NOT CONTRADICTED', 'NOT-CONTRADICTED', 'CONTRADICTED')).replace('-', ' ')
            e.update(reread=verdict, reread_usd=m.get('usd'), status='false detected' if verdict == 'CONTRADICTED' else f'false added: {verdict}')
        else:
            g = (HERE / 'prompts' / 'CONTRADICTOR-REREAD-MISS.md').read_text()
            frag = f"{e['claim']}\nWhy: {e['why']}\nX side: {', '.join(e['refs_X'])}\nY side: {', '.join(e['refs_Y'])}"
            p = W.fill(g, {'FRAGMENT': frag, 'EXTRACTS': extracts([r for r in e['refs'] if r['side'] == 'X'], xb, yb)})
            txt, m = host_call(host, model, p, trace); costs['rereads'] += m.get('usd') or 0; up = (txt or '').upper()
            verdict = first_verdict(up, ('NOT FOUND', 'FOUND', 'ABSENT')).replace('NOT FOUND', 'ABSENT')
            e.update(reread=verdict, reread_usd=m.get('usd'), status='miss verified' if verdict == 'FOUND' else f'miss false: {verdict}')


def receipt(run, d, rec):
    (run / 'contradictor.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1) + '\n'); chown(run)


def main(argv=None):
    global MAX_USD
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('run'); ap.add_argument('--families', nargs='*'); ap.add_argument('--host', choices=['claude', 'openai']); ap.add_argument('--model')
    ap.add_argument('--y-cap', type=int, default=Y_CAP); ap.add_argument('--max-usd', type=float, default=MAX_USD)
    ap.add_argument('--prompts-only', action='store_true', help='build the prompt and the receipt without calling any model')
    ap.add_argument('--T'); ap.add_argument('--request'); ap.add_argument('--target')
    a = ap.parse_args(argv)
    MAX_USD = a.max_usd
    run = pathlib.Path(a.run).resolve(); d = run / 'state' / 'contradictor'; d.mkdir(parents=True, exist_ok=True)
    fams = families(a.families)
    if not fams:
        rec = dict(status='absent', note='no contradictor configured (VP_CONTRADICTORS, ~/.config/vp/contradictors or tools/config.json contradictor.families); report unchanged', utc=utc())
        receipt(run, d, rec); print(json.dumps(rec, ensure_ascii=False)); return 0
    wr = run / 'state' / 'whole-reading'
    if not (run / 'REPORT.md').exists() or not (wr / 'material-Y.txt').exists() or not (wr / 'material-X.txt').exists():
        rec = dict(status='skipped', families=fams, note='REPORT.md and the whole-reading material (state/whole-reading/material-Y.txt, material-X.txt) are required: run tools/whole_reading.py first; report unchanged', utc=utc())
        receipt(run, d, rec); print(json.dumps(rec, ensure_ascii=False)); return 0
    report = (run / 'REPORT.md').read_text(errors='replace'); x = (wr / 'material-X.txt').read_text(errors='replace'); y_full = (wr / 'material-Y.txt').read_text(errors='replace')
    y, excluded = truncate_y(y_full, a.y_cap); xb = parse_material(x); yb = parse_material(y)
    ns = SimpleNamespace(T=a.T, request=a.request, target=a.target, x_sha=None, x2_sha=None, y_sha=None, x_name=None, x2_name=None, y_name=None, x_repo=None, x2_repo=None)
    ns = W.from_scope(run, ns)
    p = build_prompt(ns, report, y, x, xb, yb); (d / 'PROMPT.md').write_text(p)
    material = dict(y_chars=len(y), y_chars_full=len(y_full), y_cap=a.y_cap, y_truncated=bool(excluded), y_files_not_included=len(excluded), y_blocks=len(yb), x_chars=len(x), x_blocks=len(xb),
                    report_chars=len(report), prompt_chars=len(p), prompt_sha256=hashlib.sha256(p.encode()).hexdigest())
    host = host_name(a); model = reread_model(a, host)
    rec = dict(status='prompts' if a.prompts_only else 'running', families={}, material=material, reread=dict(host=host, model=model or '(host default)'), utc=utc())
    if a.prompts_only:
        rec['note'] = 'prompt built, no model called'; receipt(run, d, rec); print(json.dumps(dict(status='prompts', families=fams, **material), ensure_ascii=False)); return 0
    costs = dict(contradictors=0.0, rereads=0.0); els = []
    for name in fams:
        spec = family_spec(name)
        if not spec: rec['families'][name] = dict(error='unknown family: write openai[:<model>], claude[:<model>] or <provider>:<model> with a provider of tools/config.json contradictor.providers (' + ', '.join(sorted(providers())) + ')', exploitable=False); continue
        txt, m = contradictor_call(spec, p, d, name); j = extract_json(txt or '') if txt else None
        (d / f'{fname(name)}.json').write_text(json.dumps(dict(family=name, via=spec['via'], model=spec['model'] or '(host default)', raw=(txt or '')[:200000], json=j, measure=m, utc=utc()), ensure_ascii=False, indent=1) + '\n')
        costs['contradictors'] += float(m.get('usd') or 0)
        fam = dict(via=spec['via'], kind=spec['kind'], model=spec['model'] or '(host default)', usd=m.get('usd'), cost_known=m.get('cost_known', spec['kind'] == 'cli'), seconds=m.get('seconds'), exploitable=bool(j))
        if m.get('error'): fam['error'] = m['error']; fam['note'] = m.get('note') or m.get('detail')
        elif not j: fam['error'] = 'answer is not the expected JSON'
        rec['families'][name] = fam
        if j:
            fe = analyse(name, j, report, xb, yb); els += fe
            fam.update(n_false=len(as_list(j.get('false_claims'))), n_missed=len(as_list(j.get('missed'))))
    match(els, report, host, model, d, costs)
    reread(els, report, xb, yb, host, model, d, costs)
    false_detected = [dict(family=e['family'], quote=e['quote'], evidence=e['evidence'], why=e['why'], position=e['position']) for e in els if e['status'] == 'false detected']
    verified = [dict(family=e['family'], claim=e['claim'], refs_Y=e['refs_Y'], refs_X=e['refs_X'], why=e['why']) for e in els if e['status'] == 'miss verified']
    counts = {}
    for e in els: counts[e['status']] = counts.get(e['status'], 0) + 1
    rec.update(status='done', elements=els, false_detected=false_detected, misses_verified=verified, counts=counts,
               cost_usd=dict(contradictors=round(costs['contradictors'], 4), rereads=round(costs['rereads'], 4), total=round(costs['contradictors'] + costs['rereads'], 4), cap=MAX_USD),
               note=('apply: for each "false detected", annotate the finding that carries the quotation "contradicted by <family>: <why>" and keep it out of the executive summary and the verdicts; '
                     'for each "miss verified", add a finding with its references (verified downstream like any other, SKILL.md section 7); state in the methodology appendix the families, '
                     'the counts (false detected / false added / misses verified / misses false or not exclusive) and the cost; everything else stays in contradictor.json'), utc=utc())
    receipt(run, d, rec)
    print(json.dumps(dict(status='done', families={k: (v.get('error') or f"ok ({v.get('n_false', 0)} false, {v.get('n_missed', 0)} missed)") for k, v in rec['families'].items()},
                          false_detected=len(false_detected), misses_verified=len(verified), counts=counts, cost_usd=rec['cost_usd']['total'], file=str(run / 'contradictor.json'), note=rec['note']), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
