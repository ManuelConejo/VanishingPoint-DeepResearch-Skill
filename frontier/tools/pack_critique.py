#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare the material for the critique of the test PROTOCOL by another model family (SKILL.md step 4). Offline.

Writes <dir>/critique-pack/ (recreated at each call; the tool only ever deletes a pack it created itself):
  PROTOCOL.md  the idea, the hypotheses, rivals and variants with their references, and every test with its whole grid;
  PROMPT.md    prompts/CRITIQUE-PROTOCOL.md followed by PROTOCOL.md: the single file a critic reads (a sub-agent, or the
               other family's CLI as a sub-process); it asks for items and a verdict per test and per trap;
  with --vp-run NAME (a VP run of intake.json vp.runs, normally the run whose sources back the hypotheses), a directory
  the VP contradictor accepts in general mode: REPORT.md = PROMPT.md (the critique protocol first, then the protocol to
  critique), card.json and sources/ copied from that VP run. The command to run is printed ("vp_command"): VP's
  tools/contradictor.py in general mode, with --request naming the critique protocol and --T <T of intake.json>. VP is not
  modified: its contradictor keeps its own answer format (false claims, missed angles), which has no trap verdicts.
The critic's raw answer is saved as is in the working directory ("raw_output", default critique-raw.txt) by whoever
receives it (the sub-agent writes it itself, or the sub-process output is saved unchanged); then
`pack_critique.py DIR --receipt <raw file>` prints {"raw_output", "raw_sha256"} for critique.json (the file must be inside
DIR; a file inside critique-pack/, such as the contradictor's contradictor.json, is first copied byte for byte to
DIR/critique-raw.<ext>, because the pack is recreated by every call). Prints one JSON object (paths, commands, next step). Exit code 2 when tests.json or hypotheses.json is missing, the
VP run is unknown, or the receipt file is missing or outside DIR.

Usage: pack_critique.py DIR [--vp-run NAME]
       pack_critique.py DIR --receipt RAW_FILE
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ written in the skill directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

FRONTIER = Path(__file__).resolve().parent.parent
MARKER = '.frontier-critique-pack'
RAW_DEFAULT = 'critique-raw.txt'


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def refs_text(refs):
    out = []
    for r in refs or []:
        if isinstance(r, dict):
            s = r.get('id', '?')
            if r.get('says'):
                s += ' ("%s")' % r['says']
            out.append(s)
    return '; '.join(out) or 'none'


def protocol_md(intake, hy, tj):
    L = ['# Test protocol to critique', '']
    if intake:
        L += ['Idea: %s' % intake.get('idea', ''), 'Domain: %s. T: %s.' % (intake.get('domain', ''), intake.get('T', '')), '']
    L.append('## Hypotheses')
    for h in hy.get('hypotheses', []):
        L.append('- %s (load-bearing): %s. For: %s. Against: %s.' % (h.get('id'), h.get('statement'),
                                                                    refs_text(h.get('for')), refs_text(h.get('against'))))
    for r in hy.get('rivals', []):
        L.append('- %s (rival): %s. Why plausible: %s. For: %s.' % (r.get('id'), r.get('statement'),
                                                                   r.get('why_plausible'), refs_text(r.get('for'))))
    for v in hy.get('repairable_variants', []):
        L.append('- %s (repairable variant): %s. Repairs: %s.' % (v.get('id'), v.get('statement'), v.get('repairs')))
    for t in tj.get('tests', []):
        L += ['', '## %s: %s' % (t.get('id'), t.get('title'))]
        L.append('- Competing hypotheses: %s' % ', '.join(map(str, t.get('competing_hypotheses') or [])))
        for p in t.get('predictions') or []:
            L.append('- Prediction of %s: %s; %s; interval %s %s' % (p.get('hypothesis'), p.get('direction'),
                                                                      p.get('magnitude', ''), p.get('interval', 'none'),
                                                                      p.get('unit', '')))
        L.append('- Compatible with both: %s' % t.get('compatible_with_both'))
        L.append('- Unexpected under both: %s' % t.get('unexpected_under_both'))
        L.append('- Decisive intervention: %s' % json.dumps(t.get('decisive_intervention'), ensure_ascii=False))
        L.append('- Sensitivity: %s' % json.dumps(t.get('sensitivity'), ensure_ascii=False))
        L.append('- Decision rule: %s' % json.dumps(t.get('decision_rule'), ensure_ascii=False))
        L.append('- Pre-critique checklist (host answers and locations in tests.json): %s' %
                 json.dumps(t.get('pre_critique', 'missing [PITFALL-CHECK]'), ensure_ascii=False))
        if t.get('kind') == 'prospective':
            L.append('- Prospective start action: %s; read-out date: %s' %
                     (t.get('start_action', 'missing [PROSPECTIVE]'), t.get('readout_date', 'missing [PROSPECTIVE]')))
        L.append('- Feasibility: %s' % json.dumps(t.get('feasibility'), ensure_ascii=False))
        L.append('- A language model judges on history: %s; L0 leakage control: %s' % (
            t.get('llm_judges_history'), json.dumps(t.get('l0_leakage_control'), ensure_ascii=False)))
        L.append('- Traps: %s' % json.dumps(t.get('traps'), ensure_ascii=False))
    L += ['', '## Ranking', json.dumps(tj.get('ranking'), ensure_ascii=False), '']
    return '\n'.join(L)


def receipt(work, raw):
    rp = Path(raw)
    p = rp if rp.is_absolute() else work / rp
    try:
        rel = p.resolve().relative_to(work)
    except ValueError:
        return None, 'the raw answer %s must be inside %s' % (raw, work)
    if p.is_symlink() or not p.is_file():
        return None, 'the raw answer %s is missing (or a symbolic link)' % raw
    if rel.parts and rel.parts[0] == 'critique-pack':
        # the pack is recreated by every call of this tool: keep the raw answer next to critique.json, byte for byte
        dest = work / ('critique-raw' + (p.suffix or '.txt'))
        shutil.copyfile(str(p), str(dest))
        p, rel = dest, dest.relative_to(work)
    return {'status': 'ok', 'raw_output': rel.as_posix(), 'raw_sha256': common.sha256_file(p),
            'next': 'copy raw_output and raw_sha256 into critique.json; copy the items and trap verdicts word for word'}, None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dir')
    ap.add_argument('--vp-run')
    ap.add_argument('--receipt')
    a = ap.parse_args(argv)
    work = Path(a.dir).resolve()

    def fail(msg):
        print(json.dumps({'status': 'refused', 'reason': msg}))
        return 2

    if a.receipt:
        out, err = receipt(work, a.receipt)
        if err:
            return fail(err)
        print(json.dumps(out, indent=2))
        return 0
    try:
        tj = load(work / 'tests.json')
        hy = load(work / 'hypotheses.json')
    except (OSError, ValueError) as e:
        return fail('tests.json and hypotheses.json are required (%s)' % e)
    try:
        intake = load(work / 'intake.json')
    except (OSError, ValueError):
        intake = {}
    vp_run_dir = None
    if a.vp_run:
        runs = (intake.get('vp') or {}).get('runs') or {}
        path = runs.get(a.vp_run)
        if not isinstance(path, str):
            return fail('VP run %r is not listed in intake.json vp.runs' % a.vp_run)
        vp_run_dir = Path(path) if Path(path).is_absolute() else work / path
        if not (vp_run_dir / 'card.json').exists():
            return fail('VP run %s has no card.json' % vp_run_dir)
    pack = work / 'critique-pack'
    if pack.exists():
        if not (pack / MARKER).exists():
            return fail('%s exists and was not created by this tool: not touched' % pack)
        shutil.rmtree(str(pack))
    pack.mkdir()
    (pack / MARKER).write_text('created by frontier/tools/pack_critique.py\n', encoding='utf-8')
    protocol = protocol_md(intake, hy, tj)
    (pack / 'PROTOCOL.md').write_text(protocol, encoding='utf-8')
    prompt = (FRONTIER / 'prompts' / 'CRITIQUE-PROTOCOL.md').read_text(encoding='utf-8')
    full = prompt.rstrip() + '\n\n---\n\n' + protocol
    (pack / 'PROMPT.md').write_text(full, encoding='utf-8')
    out = {'status': 'ok', 'pack': str(pack), 'protocol': str(pack / 'PROTOCOL.md'), 'prompt': str(pack / 'PROMPT.md'),
           'raw_output': str(work / RAW_DEFAULT),
           'next': 'have PROMPT.md answered by a critic of another model family when one is configured; save its answer '
                   'unchanged as raw_output, run pack_critique.py DIR --receipt %s, then write critique.json (SKILL.md '
                   'step 4)' % RAW_DEFAULT}
    if vp_run_dir is not None:
        (pack / 'REPORT.md').write_text(full, encoding='utf-8')
        shutil.copy2(str(vp_run_dir / 'card.json'), str(pack / 'card.json'))
        if (vp_run_dir / 'sources').is_dir():
            shutil.copytree(str(vp_run_dir / 'sources'), str(pack / 'sources'))
        vp_dir = (intake.get('vp') or {}).get('dir') or '<VP>'
        if vp_dir != '<VP>' and not Path(vp_dir).is_absolute():
            vp_dir = str((work / vp_dir).resolve())
        request = ('Critique the test protocol in REPORT.md as its first part (Frontier CRITIQUE-PROTOCOL.md) '
                   'instructs: false discrimination, missing controls, leakage, traps, rule loopholes, power, feasibility.')
        out['vp_command'] = ('python3 -I "%s/tools/contradictor.py" "%s" --mode general --plugin "%s/plugins/<d>.md" '
                             '--T %s --request "%s"' % (vp_dir, pack, vp_dir, intake.get('T', '<T>'), request))
        out['raw_output'] = str(pack / 'contradictor.json')
    print(json.dumps(out, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
