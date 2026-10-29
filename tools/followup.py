#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Follow-up in the conversation (SKILL.md "Follow-up in the conversation"): "dig into point 3", "and for France?" after a finished run.
Standard library, no network, no model. Prepares a short complementary run INSIDE the parent's directory, without writing any file of the
parent: <parent>/followups/<n>/ (n = 1, 2, ... never reused; atomic creation) with
  followup.json   parent (absolute path), n, request, T and plugins inherited from the parent, language of the request, gateway run name
                  <parent run>-f<n>, call cap (config followup.call_cap), the parent finding the request points to ("point 3", "finding 3"...)
  scope.md        a skeleton to complete (criteria and 1 to 3 angles): T, plugins, language, request, parent question, the point developed,
                  and the parent's sources as "known sources" (already read: cited again by identifier, read again only for a new point)
  state/cache/    the parent's gateway cache, hard-linked (copied when links are not possible): an answer already fetched costs no network
  state/run-start.json   start time (duration in SUMMARY.md)
The follow-up then runs sections 3 to 8 in its own directory with the bounds of config `followup` (validate_card.py reads followup.json);
finish_run.py on it delivers <parent>/FOLLOWUP-<n>.md, .html and .pdf. The parent's REPORT.md, card.json, verdicts.json are never written.
Usage: followup.py PARENT_DIR "<request>" [--T YYYY-MM-DD] [--json]     Prints the directory and the commands. Exit 0; 2 on an error
(PARENT_DIR without REPORT.md: finish or resume it first, tools/resume.py).
Import: prepare(parent, request, T=None) -> dict."""
import argparse, datetime as dt, json, os, pathlib, re, shutil, sys
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P))
import report_lang as RL, resume as R, validate_card as VC   # noqa: E402,E401

CFG = VC.FOLLOWUP
POINT = re.compile(r'(?:\bpoint|\bfinding|\bconstat|\bhallazgo|\bbefund|\bpunto|\bpunkt|\bn°|#)\s*(\d{1,2})\b', re.I)


def _json(p):
    try: return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError): return None


def link_cache(src, dst):
    """Hard-links (else copies) every file of the parent's gateway cache; the gateway never rewrites a cache entry, so a link is safe."""
    n = 0
    if not src.is_dir(): return 0
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if not f.is_file() or (dst / f.name).exists(): continue
        try: os.link(f, dst / f.name)
        except OSError: shutil.copy2(f, dst / f.name)
        n += 1
    return n


def known_sources(parent):
    card = _json(parent / 'card.json') or {}
    out = []
    for k, s in sorted((card.get('sources') or {}).items(), key=lambda kv: int(re.sub(r'\D', '', kv[0]) or 0)):
        if not isinstance(s, dict): continue
        ident = next((f'{f}:{s[f]}' for f in VC.IDS if s.get(f)), '')
        out.append({'key': k, 'id': ident, 'title': str(s.get('title') or '')[:160]})
    return out


def prepare(parent, request, T=None):
    parent = pathlib.Path(parent).resolve()
    if not (parent / 'REPORT.md').is_file(): raise ValueError(f'no REPORT.md in {parent}: finish or resume the run first (tools/resume.py)')
    if (parent / 'followup.json').is_file(): raise ValueError(f'{parent} is itself a follow-up: start from its parent run')
    st = R.state(parent)
    T = T or st['T']
    if not T or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', T): raise ValueError('date T of the parent not found (run.json, journal, scope.md): give --T')
    root = parent / str(CFG.get('dir', 'followups')); root.mkdir(exist_ok=True)
    for n in range(1, 1000):
        d = root / str(n)
        try: d.mkdir(); break
        except FileExistsError: continue
    else: raise ValueError('no free follow-up number')
    (d / 'state').mkdir()
    linked = link_cache(parent / 'state' / 'cache', d / 'state' / 'cache')
    report = (parent / 'REPORT.md').read_text(encoding='utf-8', errors='replace')
    point = None
    if (m := POINT.search(request)):
        k = int(m.group(1))
        for h in RL.finding_re().finditer(RL.section(report, 'Main Analysis')):
            if int(h.group(1)) == k: point = {'n': k, 'title': h.group(2)}; break
    lang = RL.detect(request) if re.search(r'[^\W\d_]{3,}', request) else st['language']
    card = _json(parent / 'card.json') or {}
    meta = {'parent': str(parent), 'n': n, 'request': request, 'T': T, 'plugins': st['plugins'], 'language': lang,
            'parent_question': card.get('question') or '', 'run': f"{st['run'] or parent.name}-f{n}", 'cap': int(CFG.get('call_cap', 20)),
            'point': point, 'cache_files_linked': linked, 'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}
    (d / 'followup.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    (d / 'state' / 'run-start.json').write_text(json.dumps({'question': request, 'language': lang, 'created_utc': meta['created_utc']},
                                                          ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    known = known_sources(parent)
    L = [f'# Scope - follow-up {n} of {parent.name}', '',
         f"T = {T} (inherited from the parent run). Plugins: {', '.join(st['plugins']) or 'as the parent'}. Mode: standard.", '',
         f'Request: {request}', f"Parent question: {meta['parent_question']}"]
    if point: L.append(f"Point developed: {RL.LANGS['en']['finding']} {point['n']} - {point['title']} (parent REPORT.md)")
    L += ['', '## Criteria', '', 'Write here what this follow-up must answer (narrower than the parent question), its exclusions, and what would be off topic.',
          '', '## Angles', '', 'Write here 1 to 3 numbered angles that the parent run did not cover (the parent scope.md lists its own).', '',
          f'## Budget', '', f"Gateway cap {meta['cap']} calls (config followup.call_cap); one wave of 1 or 2 searchers, one complement at most.", '',
          '## Known sources (parent bibliography: already read; cite them by identifier, read again only for a new point)', '']
    L += [f"- {s['key']}: {s['id']} - {s['title']}" for s in known] or ['- none']
    L += ['', '## Waves', '']
    (d / 'scope.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    meta['dir'] = str(d); meta['deliverable'] = str(parent / f'FOLLOWUP-{n}.md')
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser(description='Prepare a follow-up run inside a finished run (no model, no network).')
    ap.add_argument('parent'); ap.add_argument('request', nargs='+'); ap.add_argument('--T'); ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    try: m = prepare(a.parent, ' '.join(a.request), a.T)
    except (ValueError, OSError) as e: print(f'followup.py: {e}', file=sys.stderr); return 2
    if a.json: print(json.dumps(m, ensure_ascii=False, indent=1)); return 0
    plug = ' '.join(f'--plugin {p}' for p in m['plugins'])
    print(m['dir'])
    print(f"T = {m['T']}; plugins: {', '.join(m['plugins']) or 'as the parent'}; language: {m['language']}; cap {m['cap']} calls; "
          f"parent cache: {m['cache_files_linked']} file(s) linked" + (f"; point: {m['point']['n']} - {m['point']['title']}" if m['point'] else ''))
    print(f"gateway: python3 -I {P}/gateway.py {plug} --T {m['T']} --run {m['run']} --state {m['dir']}/state --cap {m['cap']} <command> \"<argument>\"")
    print(f"verifier: python3 -I {P}/verifier.py verify --card {m['dir']}/card.json --out {m['dir']}/verdicts.json --T {m['T']} {plug} "
          f"--run {m['run']} --state {m['dir']}/state --sources {m['dir']}/sources --filter")
    print(f"end: python3 -I {P}/finish_run.py {m['dir']} --T {m['T']} {plug}   (delivers {m['deliverable']})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
