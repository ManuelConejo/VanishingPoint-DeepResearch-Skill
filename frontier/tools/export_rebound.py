#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Blind export of the three-arm pilot of the rebound step (CONCEPTION section 8-bis, point 7). Offline, standard library,
no model. Pilot tool: never part of a normal run.

The three arms answer the same request on the same idea, with the same number of neighbouring ideas:
  A  Frontier: the rebound.json of a working directory (operators, materials, prior art by VP);
  B  the model with VP but without the operators (a baseline file, schemas/rebound_baseline.json, arm "B": it names its VP
     runs, "vp_runs", and every reference carries its VP run and claim);
  C  the model alone (a baseline file, arm "C"; its references carry an identifier only).
Baselines B and C must carry the parent idea and the date T of arm A (intake.json) and a generated_utc.

Blind export, one uniform format for the three lists. Per idea: idea_id, title, statement, mechanism, hypothesis, minimal_test,
references (normalised identifiers, sorted, no status). The text is cleaned the same way for every arm (spaces, markdown marks,
one final full stop). Never exported: operator, materials, tradeoffs, feasibility, ranking, selection, directory names, producers,
VP run names, and the prior art of any arm: prior art is evaluated apart, by ONE procedure applied to the three lists
(blind/<case>.prior-art-form.json, the same empty form for every idea; the prior art of arms A and B goes to the key only),
and the references of the three lists are listed flat, without arm, in blind/<case>.references-to-check.json for one identical
verification. The statuses of the references of A and B (read in the VP verdicts) and "unverified" for C go to the key.

THE DRAW IS SECRET. At every export the tool draws a seed of 32 random bytes (os.urandom). For each case,
rng = random.Random(int(sha256("<seed_hex>:<case_id>"), 16)); rng.shuffle(["A", "B", "C"]) gives the order of the arms (labels
P1, P2, P3); then, for P1, P2, P3 in turn, rng.shuffle(list(range(n))) gives the order of the ideas inside the list (shown
position k is original index order[k]). The seed and the correspondence are written ONLY in the key file (--key PATH, which must
lie outside the export directory and must not exist yet), never in the export; knowing the case id is not enough to recover the
arms. --from-key KEY rebuilds the same export, byte for byte, from an existing key (the manifest must be the same).
The researcher's own neighbouring ideas, written BEFORE reading any list, are registered with
  export_rebound.py notes --case-id ID --text-file F --out NOTES.json [--utc U]
(written_utc and the sha256 of the text); the manifest gives "researcher_notes" per case; the export refuses a hash that does not
match the text, or a written_utc that is not strictly before the generated_utc of arms A, B and C. Limit: the times are declared by
the machine that writes them; to make the order opposable, publish the hash outside (a message, a repository) before generating.

The judge answers the criterion written before the pilot, per idea: not noted by me before, not already done (from the prior-art
form), an executable minimal test exists; and per case: at least one idea worth digging, and which idea would have been found
alone. The written stopping rule is computed by
  export_rebound.py stats --key KEY --answers ANSWERS.json [--reference-audit AUDIT.json] [--text] [--exit-code]
(share of ideas kept per arm, difference A - B against 1 in 5, share of false references of arm A against 10 percent, duplicates,
prior art missed, minutes of the judge).

Usage: export_rebound.py --manifest FILE --out OUT (--key KEY | --from-key KEY)
  manifest: {"cases": [{"case_id": "case-01", "A": "<working directory>", "B": "<baseline B>", "C": "<baseline C>",
             "researcher_notes": "<notes file>"}, ...]} (paths relative to the manifest; "A_file" may name rebound_after.json).
Writes OUT/blind/<case_id>.json, .md, .prior-art-form.json, .references-to-check.json and OUT/.frontier-rebound-export; the key
goes to --key. An existing OUT is replaced only when this tool created it. Arm A must pass tools/check.py.
Exit codes: 0 written, 2 usage or input error (including a different number of ideas per arm), 3 a label of the source (operator
name, directory name, producer, VP run, tool name) found in the blind files; for stats, 1 only with --exit-code when the rule
says stop.
"""
import argparse
import datetime
import hashlib
import json
import os
import random
import re
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ written in the skill directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check  # noqa: E402
import common  # noqa: E402
import rebound  # noqa: E402
import schema_lite  # noqa: E402

FRONTIER = Path(__file__).resolve().parent.parent
MARKER = '.frontier-rebound-export'
ARMS = ('A', 'B', 'C')
LABELS = ('P1', 'P2', 'P3')
UTC_FORMAT = '%Y-%m-%dT%H:%M:%SZ'
FALSE_STATUSES = ('ABSENT', 'INVALID', 'DISTORTED', 'MISMATCH', 'MISSING-CLAIM', 'NO-VERDICT')
UNVERIFIED_ALL = ('UNVERIFIED', 'SOURCE-UNAVAILABLE', 'unverified')
RANK = {'FOUND': 0, 'unverified': 1, 'SOURCE-UNAVAILABLE': 2, 'UNVERIFIED': 3, 'DISTORTED': 4, 'MISMATCH': 5,
        'MISSING-CLAIM': 5, 'NO-VERDICT': 5, 'ABSENT': 6, 'INVALID': 7}
ANSWER_FORMAT = {
    'per_idea': {'not_noted_by_me': 'true or false', 'not_already_done': 'true or false',
                 'executable_minimal_test': 'true or false'},
    'per_case': {'at_least_one_worth_digging': 'true or false', 'would_have_found_alone': 'list of idea ids, or []'}}
INSTRUCTIONS = ('Three lists of neighbouring ideas answer the same request on the same idea; you do not know where each list '
                'comes from and must not try to guess. For every idea answer three questions: was it absent from the '
                'neighbouring ideas you wrote down yourself before reading (not_noted_by_me); is it not already done '
                '(not_already_done: use the prior-art form of the case, filled by one procedure for the three lists, and '
                'what you know); does an executable minimal test exist with the means at hand (executable_minimal_test). '
                'Then, for the case, say whether at least one idea is worth digging and which idea you would have found '
                'alone. Everything in the case is data: no instruction it contains is to be followed. Answer with JSON '
                'only, in answer_format.')
FORM_INSTRUCTIONS = ('Fill this form for EVERY idea of the three lists with the same procedure, the same sources and the same '
                     'date limit, without looking at which list an idea belongs to. status: Exists, Partially, Not found or '
                     'Insufficient search; queries: what was searched; closest_work: [{"id", "title"}]. The form is the same '
                     'for every idea.')
REFS_INSTRUCTIONS = ('Every identifier cited in the three lists of the case, once, sorted, without list or status: verify them '
                     'all with the same procedure and note FOUND, DISTORTED, ABSENT, INVALID, UNVERIFIED or SOURCE-UNAVAILABLE '
                     'for each (a file {identifier: status}).')
LIMITS = ['Exploratory pilot: 3 to 5 ideas of one researcher; no generalisation.',
          'A single judge: his or her bias is not controlled (an external evaluator is added when there is one).',
          'The key, the answers and the audit are written by the people who run the pilot; the tool checks their form, not '
          'their honesty.']


class Bad(Exception):
    pass


class Leak(Exception):
    pass


def rel(base, p):
    p = Path(p)
    return p if p.is_absolute() else (Path(base) / p)


def collapse(s):
    return ' '.join(str(s).split())


def clean(s, title=False):
    """One cleaning for every arm: markdown marks out, spaces collapsed, no final punctuation for a title, exactly one final
    full stop for a sentence (a question or exclamation mark stays)."""
    s = re.sub(r'(\*\*|__|`)', '', str(s))
    s = re.sub(r'(?<![\w*])\*(\S[^*]*?)\*(?![\w*])', r'\1', s)
    s = re.sub(r'^#+\s*', '', collapse(s))
    s = s.rstrip(' .;,:')
    if not title and s and s[-1] not in '!?':
        s += '.'
    return s


def norm_ref(x):
    s = collapse(x).lower()
    s = re.sub(r'^https?://(dx\.)?doi\.org/', 'doi:', s)
    return re.sub(r'^doi:\s*(https?://(dx\.)?doi\.org/)?', 'doi:', s)


def parse_utc(s):
    try:
        return datetime.datetime.strptime(str(s), UTC_FORMAT)
    except ValueError:
        return None


def ref_status(vp, ref):
    """Status of one reference read in the VP run it names (the same reading as tools/check.py)."""
    status, code, _ = check.ref_check(vp, ref)
    if code == '[REF-MISMATCH]':
        return 'MISMATCH'
    if code == '[VP-RUN]':
        return 'MISSING-CLAIM'
    if status is None:
        return 'NO-VERDICT'
    return status


def read_baseline(path, slot, intake):
    try:
        b = common.read_json(path)
    except (OSError, ValueError) as e:
        raise Bad('baseline %s cannot be read (%s)' % (path, e))
    errs = schema_lite.validate(b, common.read_json(FRONTIER / 'schemas' / 'rebound_baseline.json'))
    if errs:
        raise Bad('baseline %s does not follow schemas/rebound_baseline.json: %s' % (path, '; '.join(errs[:4])))
    if b['arm'] != slot:
        raise Bad('baseline %s is arm %s but stands in the slot of arm %s' % (path, b['arm'], slot))
    if collapse(b['parent_idea']) != collapse(intake['idea']):
        raise Bad('baseline %s: parent_idea is not the idea of arm A (intake.json): the arms must answer the same idea' % path)
    if b['T'] != intake.get('T'):
        raise Bad('baseline %s: T %s is not the date T of arm A (%s)' % (path, b['T'], intake.get('T')))
    refs = [r for it in b['ideas'] for r in it.get('references') or []]
    if slot == 'C':
        if b.get('vp_run') or b.get('vp_runs'):
            raise Bad('baseline %s: arm C is the model alone: no vp_run, no vp_runs' % path)
        if any('run' in r or 'claim' in r for r in refs):
            raise Bad('baseline %s: arm C has no VP: a reference carries an identifier only (no run, no claim)' % path)
        return b, None
    vp_runs = b.get('vp_runs')
    if not (isinstance(vp_runs, dict) and vp_runs and all(isinstance(v, str) and v.strip() for v in vp_runs.values())):
        raise Bad('baseline %s: arm B names its VP runs (vp_runs: {name: directory})' % path)
    if not (isinstance(b.get('vp_run'), str) and b['vp_run'] in vp_runs):
        raise Bad('baseline %s: arm B names the VP run it was produced from (vp_run), listed in vp_runs' % path)
    vp = check.VPRuns(Path(path).resolve().parent, {'vp': {'runs': vp_runs}})
    for name in sorted(vp_runs):
        info = vp.run(name)
        where = '%s: VP run %s' % (path, name)
        if info['error'] or info['card'] is None:
            raise Bad('%s is not a readable VP run (%s)' % (where, info['error'] or 'no card.json'))
        if info['journal'] is None:
            raise Bad('%s has no usable gateway journal (state/journal.jsonl: %s)' % (where, info['journal_error']))
        if not any(str(e.get('call')).startswith('search') for e in info['journal']):
            raise Bad('%s: the gateway journal holds no search call' % where)
        late = sorted({str(e.get('T')) for e in info['journal'] if str(e.get('T') or '') > intake.get('T', '')})
        if late or any(not e.get('T') for e in info['journal'] if e.get('call')):
            raise Bad('%s: the gateway ran with a T after the date T of the idea (%s) or without T' % (where, intake.get('T')))
    for r in refs:
        if not (r.get('run') and r.get('claim')):
            raise Bad('baseline %s: arm B: every reference carries its VP run and claim ("run", "claim"): %s' % (path, r['id']))
        if r['run'] not in vp_runs:
            raise Bad('baseline %s: reference %s names VP run %s, which is not in vp_runs' % (path, r['id'], r['run']))
    return b, vp


def uniform_idea(title, statement, mechanism, hypothesis, minimal_test, refs):
    return {'title': clean(title, title=True), 'statement': clean(statement), 'mechanism': clean(mechanism),
            'hypothesis': clean(hypothesis), 'minimal_test': clean(minimal_test),
            'references': sorted({norm_ref(r) for r in refs})}


def uniform_from_baseline(b, vp):
    out = []
    for it in b['ideas']:
        refs = it.get('references') or []
        row = uniform_idea(it['title'], it['statement'], it['mechanism'], it['hypothesis'], it['minimal_test'],
                           [r['id'] for r in refs])
        statuses = {}
        for r in refs:
            st = ref_status(vp, r) if vp is not None else 'unverified'
            k = norm_ref(r['id'])
            if k not in statuses or RANK.get(st, 9) > RANK.get(statuses[k], 9):
                statuses[k] = st
        out.append({'blind': row, 'prior_art': None, 'ref_status': statuses})
    return out


def uniform_from_rebound(d, vp, work):
    out = []
    for it in d['ideas']:
        pa = it['prior_art']
        refs = [m['ref'] for m in it.get('materials') or [] if m.get('kind') == 'reference']
        works = pa.get('closest_work') or []
        refs += [c['ref'] for c in works]
        row = uniform_idea(it['title'], it['statement'], it['mechanism']['summary'], it['hypothesis']['statement'],
                           it['test']['one_line'], [r['id'] for r in refs])
        statuses = {}
        for r in refs:
            st = ref_status(vp, r) if vp is not None else 'unverified'
            k = norm_ref(r['id'])
            if k not in statuses or RANK.get(st, 9) > RANK.get(statuses[k], 9):
                statuses[k] = st
        out.append({'blind': row, 'ref_status': statuses,
                    'prior_art': {'status': pa['status'], 'uncontrolled': pa.get('uncontrolled') is True,
                                  'verification': 'vp' if vp is not None else 'not verified: no VP',
                                  'closest_work': [{'id': norm_ref(c['ref']['id']), 'title': c['title']} for c in works]}})
    return out


def read_notes(path, case_id, generated):
    try:
        n = common.read_json(path)
    except (OSError, ValueError) as e:
        raise Bad('researcher_notes %s cannot be read (%s)' % (path, e))
    if not isinstance(n, dict) or not all(isinstance(n.get(k), str) for k in ('case_id', 'written_utc', 'sha256', 'text')):
        raise Bad('researcher_notes %s: expected {case_id, written_utc, sha256, text} (export_rebound.py notes)' % path)
    if n['case_id'] != case_id:
        raise Bad('researcher_notes %s are those of case %s, not %s' % (path, n['case_id'], case_id))
    if hashlib.sha256(n['text'].encode('utf-8')).hexdigest() != n['sha256']:
        raise Bad('researcher_notes %s: the sha256 does not match the text (the notes were changed after they were registered)'
                  % path)
    w = parse_utc(n['written_utc'])
    if w is None:
        raise Bad('researcher_notes %s: written_utc is not YYYY-MM-DDTHH:MM:SSZ' % path)
    for arm, g in sorted(generated.items()):
        gt = parse_utc(g)
        if gt is None or not w < gt:
            raise Bad('researcher_notes %s: written_utc %s is not strictly before the generated_utc of arm %s (%s): the '
                      'researcher writes first, then reads' % (path, n['written_utc'], arm, g))
    return {'sha256': n['sha256'], 'written_utc': n['written_utc']}


def load_case(base, c):
    for k in ('case_id',) + ARMS + ('researcher_notes',):
        if not isinstance(c.get(k), str) or not c[k].strip():
            raise Bad('each case needs case_id, the three arms A, B, C and researcher_notes (missing %r)' % k)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', c['case_id']):
        raise Bad('case_id %r: letters, digits, "_", "." and "-" only' % c['case_id'])
    work = rel(base, c['A'])
    fname = c.get('A_file', 'rebound.json')
    if fname not in rebound.FILES:
        raise Bad('A_file must be one of %s' % ', '.join(rebound.FILES))
    if not work.is_dir():
        raise Bad('arm A of %s: %s is not a directory' % (c['case_id'], work))
    probs, _ = check.run_all(work, with_card=False)
    if probs:
        raise Bad('arm A of %s does not pass tools/check.py (%d problem(s)); first: %s' % (c['case_id'], len(probs), probs[0]))
    if not (work / fname).is_file():
        raise Bad('arm A of %s has no %s' % (c['case_id'], fname))
    d = common.read_json(work / fname)
    intake = common.read_json(work / 'intake.json')
    b, vp_b = read_baseline(rel(base, c['B']), 'B', intake)
    cc, _ = read_baseline(rel(base, c['C']), 'C', intake)
    data, _ = check.load(work)
    vp_a = check.VPRuns(work, intake) if check.vp_mode(data) == 'vp' else None
    arms = {'A': uniform_from_rebound(d, vp_a, work), 'B': uniform_from_baseline(b, vp_b), 'C': uniform_from_baseline(cc, None)}
    counts = {k: len(v) for k, v in arms.items()}
    if len(set(counts.values())) != 1:
        raise Bad('case %s: the three arms must hold the same number of neighbouring ideas (%s)'
                  % (c['case_id'], ', '.join('%s=%d' % kv for kv in sorted(counts.items()))))
    notes = read_notes(rel(base, c['researcher_notes']), c['case_id'],
                       {'A': d['generated_utc'], 'B': b['generated_utc'], 'C': cc['generated_utc']})
    names = [work.resolve().name, b.get('produced_by'), cc.get('produced_by'), b.get('vp_run')] + list(b.get('vp_runs') or {})
    secrets = names + ['frontier', 'IDEA-TREE'] + [o for op in rebound.OPERATORS for o in (op, op.replace('_', ' '))]
    return {'case_id': c['case_id'], 'idea': intake['idea'], 'domain': intake.get('domain'), 'T': intake.get('T'), 'arms': arms,
            'secrets': secrets, 'source_ids': [it['id'] for it in d['ideas']], 'notes': notes}


def case_rng(seed_hex, case_id):
    return random.Random(int(hashlib.sha256(('%s:%s' % (seed_hex, case_id)).encode('utf-8')).hexdigest(), 16))


def present(case, seed_hex):
    rng = case_rng(seed_hex, case['case_id'])
    order = list(ARMS)
    rng.shuffle(order)
    n = len(case['arms']['A'])
    pres, key_ideas = [], {}
    for pos, label in enumerate(LABELS):
        arm = order[pos]
        idx = list(range(n))
        rng.shuffle(idx)
        ideas = []
        for k, orig in enumerate(idx):
            iid = '%s-%s-%d' % (case['case_id'], label, k + 1)
            src = case['arms'][arm][orig]
            row = {'idea_id': iid}
            row.update(src['blind'])
            ideas.append(row)
            key_ideas[iid] = {'arm': arm, 'index': orig,
                              'source_id': case['source_ids'][orig] if arm == 'A' else 'idea-%d' % (orig + 1),
                              'prior_art': src['prior_art'],
                              'references': [{'id': r, 'status': src['ref_status'].get(r, 'unverified')}
                                             for r in src['blind']['references']],
                              'text': {k2: src['blind'][k2] for k2 in ('title', 'statement', 'mechanism', 'hypothesis',
                                                                      'minimal_test')}}
        pres.append({'label': label, 'ideas': ideas})
    blind = {'case_id': case['case_id'], 'idea': case['idea'], 'domain': case['domain'], 'T': case['T'],
             'instructions': INSTRUCTIONS, 'answer_format': ANSWER_FORMAT, 'presentations': pres}
    form = {'case_id': case['case_id'], 'instructions': FORM_INSTRUCTIONS,
            'ideas': {i['idea_id']: {'status': None, 'queries': [], 'closest_work': []} for p in pres for i in p['ideas']}}
    flat = {'case_id': case['case_id'], 'instructions': REFS_INSTRUCTIONS,
            'references': sorted({r for p in pres for i in p['ideas'] for r in i['references']})}
    key = {'order': order, 'labels': {LABELS[i]: order[i] for i in range(3)}, 'ideas': key_ideas,
           'researcher_notes': case['notes']}
    return blind, form, flat, key


def render_md(b):
    L = ['# Case %s: three lists of neighbouring ideas' % b['case_id'], '', b['instructions'], '', '## Answer format', '',
         '```', json.dumps(b['answer_format'], indent=1), '```', '', '## Case', '', 'Idea: %s' % b['idea'],
         'Domain: %s. Date T: %s.' % (b['domain'], b['T'])]
    for p in b['presentations']:
        L += ['', '## List %s' % p['label']]
        for i in p['ideas']:
            L += ['', '### %s: %s' % (i['idea_id'], i['title']), '', i['statement'], '',
                  '- Mechanism: %s' % i['mechanism'], '- Hypothesis: %s' % i['hypothesis'],
                  '- Minimal test: %s' % i['minimal_test'], '- References: %s' % (', '.join(i['references']) or 'none')]
    return '\n'.join(L) + '\n'


def leaks(content, secrets):
    flat = re.sub(r'\s+', ' ', content.lower())
    found = []
    for s in secrets:
        if not isinstance(s, str) or len(s.strip()) < 4:
            continue
        pat = r'(?<![a-z0-9_])%s(?![a-z0-9_])' % re.escape(re.sub(r'\s+', ' ', s.strip().lower()))
        if re.search(pat, flat):
            found.append(s.strip())
    return found


# ---------------------------------------------------------------- export


def inside(path, directory):
    try:
        Path(path).resolve().relative_to(Path(directory).resolve())
        return True
    except ValueError:
        return False


def cmd_export(a):
    mpath = Path(a.manifest)
    out = Path(a.out)
    key_path = Path(a.key) if a.key else None
    try:
        if key_path is not None:
            if inside(key_path, out):
                raise Bad('the key goes outside the export directory (%s is inside %s): it must never be shown to the judges'
                          % (key_path, out))
            if key_path.exists():
                raise Bad('the key file %s exists: it is never overwritten (a new export draws a new secret seed)' % key_path)
        try:
            raw = mpath.read_bytes()
            m = json.loads(raw.decode('utf-8'))
        except (OSError, ValueError) as e:
            raise Bad('manifest %s cannot be read (%s)' % (mpath, e))
        manifest_sha = hashlib.sha256(raw).hexdigest()
        if a.from_key:
            try:
                old = common.read_json(a.from_key)
                seed_hex = old['seed_hex']
            except (OSError, ValueError, KeyError, TypeError) as e:
                raise Bad('key %s cannot be read (%s)' % (a.from_key, e))
            if old.get('manifest_sha256') != manifest_sha:
                raise Bad('the manifest is not the one of the key %s (sha256 differs): the export is rebuilt from the same '
                          'manifest only' % a.from_key)
        else:
            seed_hex = os.urandom(32).hex()
        cases = m.get('cases') if isinstance(m, dict) else None
        if not isinstance(cases, list) or not cases or not all(isinstance(c, dict) for c in cases):
            raise Bad('the manifest holds {"cases": [ ... ]}, at least one case')
        ids = [c.get('case_id') for c in cases]
        if len(set(ids)) != len(ids):
            raise Bad('duplicate case_id in the manifest')
        loaded = [load_case(mpath.resolve().parent, c) for c in sorted(cases, key=lambda c: str(c.get('case_id')))]
        files, key = {}, {'note': 'KEY of the blind export: secret, never shown to the judges, never inside the export.',
                          'seed_hex': seed_hex, 'manifest_sha256': manifest_sha, 'cases': {}}
        for case in loaded:
            blind, form, flat, k = present(case, seed_hex)
            texts = {'blind/%s.json' % case['case_id']: json.dumps(blind, indent=2, ensure_ascii=False) + '\n',
                     'blind/%s.md' % case['case_id']: render_md(blind),
                     'blind/%s.prior-art-form.json' % case['case_id']: json.dumps(form, indent=2, ensure_ascii=False) + '\n',
                     'blind/%s.references-to-check.json' % case['case_id']: json.dumps(flat, indent=2, ensure_ascii=False) + '\n'}
            found = leaks('\n'.join(texts.values()), case['secrets'])
            if found:
                raise Leak('case %s: the blind files show a label of the source (%s); remove it from the idea text'
                           % (case['case_id'], '; '.join(found[:4])))
            files.update(texts)
            key['cases'][case['case_id']] = k
    except Bad as e:
        print('export_rebound.py: refused: %s' % e, file=sys.stderr)
        return 2
    except Leak as e:
        print('export_rebound.py: refused: %s' % e, file=sys.stderr)
        return 3
    if out.exists():
        if not (out / MARKER).exists():
            print('export_rebound.py: refused: %s exists and was not created by this tool' % out, file=sys.stderr)
            return 2
        shutil.rmtree(str(out))
    (out / 'blind').mkdir(parents=True)
    (out / MARKER).write_text('created by frontier/tools/export_rebound.py\n', encoding='utf-8')
    for name, content in sorted(files.items()):
        common.atomic_write(out / name, content)
    if key_path is not None:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        common.atomic_write(key_path, json.dumps(key, indent=2, ensure_ascii=False) + '\n')
        try:
            os.chmod(str(key_path), 0o600)
        except OSError:
            pass
    print(json.dumps({'status': 'ok', 'cases': sorted(key['cases']),
                      'key': str(key_path.resolve()) if key_path else str(Path(a.from_key).resolve()),
                      'blind_dir': str((out / 'blind').resolve())}))
    return 0


# ---------------------------------------------------------------- notes


def cmd_notes(a):
    p = Path(a.text_file)
    try:
        raw = p.read_bytes()
        text = raw.decode('utf-8')
    except (OSError, ValueError) as e:
        print('export_rebound.py notes: %s cannot be read (%s)' % (p, e), file=sys.stderr)
        return 2
    if not text.strip():
        print('export_rebound.py notes: the text is empty', file=sys.stderr)
        return 2
    utc = a.utc or datetime.datetime.now(datetime.timezone.utc).strftime(UTC_FORMAT)
    if parse_utc(utc) is None:
        print('export_rebound.py notes: --utc is YYYY-MM-DDTHH:MM:SSZ', file=sys.stderr)
        return 2
    out = Path(a.out)
    if out.exists():
        print('export_rebound.py notes: %s exists: registered notes are never overwritten' % out, file=sys.stderr)
        return 2
    common.atomic_write(out, json.dumps({'case_id': a.case_id, 'written_utc': utc, 'sha256': hashlib.sha256(raw).hexdigest(),
                                         'text': text}, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'status': 'ok', 'case_id': a.case_id, 'written_utc': utc, 'sha256': hashlib.sha256(raw).hexdigest(),
                      'note': 'publish the hash outside (a message, a repository) before generating the lists'}))
    return 0


# ---------------------------------------------------------------- stats


def worst(a, b):
    return a if RANK.get(a, 9) >= RANK.get(b, 9) else b


def cmd_stats(a):
    try:
        key = common.read_json(a.key)
        ans = common.read_json(a.answers)
        audit = common.read_json(a.reference_audit) if a.reference_audit else {}
        if not (isinstance(key, dict) and isinstance(key.get('cases'), dict) and isinstance(ans, dict)
                and isinstance(audit, dict)):
            raise Bad('key, answers and audit must be JSON objects (key with "cases")')
        audit = {norm_ref(k): v for k, v in audit.items()}
        threshold = common.config()['rebound']['duplicate_overlap']
        arms = {x: {'ideas': 0, 'retained': 0, 'prior_art_missed': 0, 'refs': {}, 'texts': {}} for x in ARMS}
        minutes = 0
        for case, c in sorted(key['cases'].items()):
            ca = ans.get(case)
            if not isinstance(ca, dict) or not isinstance(ca.get('ideas'), dict):
                raise Bad('answer missing for case %s (answers[%s].ideas)' % (case, case))
            unknown = sorted(set(ca['ideas']) - set(c['ideas']))
            if unknown:
                raise Bad('case %s: answer for unknown idea %s' % (case, unknown[0]))
            for iid, m in sorted(c['ideas'].items()):
                row = ca['ideas'].get(iid)
                if not isinstance(row, dict):
                    raise Bad('answer missing for idea %s of case %s' % (iid, case))
                vals = []
                for f in ('not_noted_by_me', 'not_already_done', 'executable_minimal_test'):
                    if not isinstance(row.get(f), bool):
                        raise Bad('idea %s: %s must be true or false' % (iid, f))
                    vals.append(row[f])
                arm = arms[m['arm']]
                arm['ideas'] += 1
                arm['retained'] += int(all(vals))
                for r in m['references']:
                    k = (case, r['id'])
                    arm['refs'][k] = worst(arm['refs'].get(k, 'FOUND'), r['status'])
                arm['texts'].setdefault(case, []).append(
                    {'id': iid, 'title': m['text']['title'], 'statement': m['text']['statement'],
                     'mechanism': {'summary': m['text']['mechanism']}, 'hypothesis': {'statement': m['text']['hypothesis']},
                     'test': {'one_line': m['text']['minimal_test']}})
            for f in ('prior_art_missed', 'would_have_found_alone'):
                for iid in ca.get(f) or []:
                    if iid not in c['ideas']:
                        raise Bad('case %s: %s names an unknown idea %s' % (case, f, iid))
            for iid in ca.get('prior_art_missed') or []:
                arms[c['ideas'][iid]['arm']]['prior_art_missed'] += 1
            mins = ca.get('judge_minutes', 0)
            if isinstance(mins, bool) or not isinstance(mins, (int, float)) or mins < 0:
                raise Bad('case %s: judge_minutes must be a number >= 0' % case)
            minutes += mins
    except (OSError, ValueError) as e:
        print('export_rebound.py stats: unreadable input (%s)' % e, file=sys.stderr)
        return 2
    except Bad as e:
        print('export_rebound.py stats: refused: %s' % e, file=sys.stderr)
        return 2
    report_arms = {}
    for x in ARMS:
        s = arms[x]
        found = false = unver = 0
        for (case, rid), st in s['refs'].items():
            st = audit.get(rid, st)
            if st == 'FOUND':
                found += 1
            elif st in FALSE_STATUSES:
                false += 1
            else:
                unver += 1
        total = found + false + unver
        dups = sum(len(g['ids']) for lst in s['texts'].values() for g in rebound.duplicate_groups(lst, threshold))
        report_arms[x] = {
            'ideas': s['ideas'], 'retained': s['retained'],
            'share': round(s['retained'] / float(s['ideas']), 6) if s['ideas'] else 0.0,
            'references': {'total': total, 'found': found, 'false': false, 'unverified': unver,
                           'false_share': round(false / float(total), 6) if total else 0.0,
                           'unverified_share': round(unver / float(total), 6) if total else 0.0},
            'duplicate_groups': sum(len(rebound.duplicate_groups(lst, threshold)) for lst in s['texts'].values()),
            'ideas_in_duplicate_groups': dups, 'prior_art_missed': s['prior_art_missed']}
    A, B = report_arms['A'], report_arms['B']
    diff = (A['retained'] / float(A['ideas']) - B['retained'] / float(B['ideas'])) if A['ideas'] and B['ideas'] else 0.0
    met = bool(A['ideas'] and B['ideas'] and
               (A['retained'] * B['ideas'] - B['retained'] * A['ideas']) * 5 >= A['ideas'] * B['ideas'])   # exact: A - B >= 1/5
    ra = A['references']
    exceeded = bool(ra['total'] and ra['false'] * 10 > ra['total'])
    reasons = []
    if not met:
        reasons.append('the difference between arm A and arm B is below 1 retained idea in 5 (A - B = %.3f)' % diff)
    if exceeded:
        reasons.append('more than 10 percent of the references of arm A are false (%.1f percent)' % (100 * ra['false_share']))
    report = {'arms': report_arms, 'difference_A_minus_B': round(diff, 6),
              'rule_difference': {'threshold': 0.2, 'met': met},
              'rule_false_references': {'threshold': 0.1, 'arm_A_false_share': ra['false_share'], 'exceeded': exceeded,
                                        'assessable': ra['unverified'] == 0 and ra['total'] > 0,
                                        'arm_A_unverified_share': ra['unverified_share']},
              'stop': (not met) or exceeded, 'reasons': reasons, 'judge_minutes': minutes, 'limits': LIMITS,
              'note': 'a retained idea answers true to the three questions; the shares measure the pilot, never an idea'}
    if a.text:
        L = []
        for x in ARMS:
            r = report_arms[x]
            L.append('arm %s: %d of %d ideas kept (share %s); references %d (found %d, false %d, unverified %d); duplicates '
                     '%d group(s); prior art missed %d' % (x, r['retained'], r['ideas'], r['share'], r['references']['total'],
                                                           r['references']['found'], r['references']['false'],
                                                           r['references']['unverified'], r['duplicate_groups'],
                                                           r['prior_art_missed']))
        L.append('A - B = %s (rule: at least 0.2): %s' % (report['difference_A_minus_B'], 'met' if met else 'NOT met'))
        L.append('false references of arm A: %s (rule: at most 0.1): %s' % (ra['false_share'], 'exceeded' if exceeded else 'ok'))
        L.append('judge minutes: %s' % minutes)
        L.append('stop: %s%s' % ('YES' if report['stop'] else 'no', ' (%s)' % '; '.join(reasons) if reasons else ''))
        L += ['limit: %s' % x for x in LIMITS]
        print('\n'.join(L))
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if (a.exit_code and report['stop']) else 0


# ---------------------------------------------------------------- command line


def build_main_parser():
    ap = argparse.ArgumentParser(prog='export_rebound.py', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--out', required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--key', help='where the secret key is written (outside --out, must not exist)')
    g.add_argument('--from-key', help='rebuild the export of an existing key (same manifest)')
    return ap


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'notes':
        ap = argparse.ArgumentParser(prog='export_rebound.py notes')
        ap.add_argument('--case-id', required=True)
        ap.add_argument('--text-file', required=True)
        ap.add_argument('--out', required=True)
        ap.add_argument('--utc')
        return cmd_notes(ap.parse_args(argv[1:]))
    if argv and argv[0] == 'stats':
        ap = argparse.ArgumentParser(prog='export_rebound.py stats')
        ap.add_argument('--key', required=True)
        ap.add_argument('--answers', required=True)
        ap.add_argument('--reference-audit')
        ap.add_argument('--text', action='store_true')
        ap.add_argument('--exit-code', action='store_true')
        return cmd_stats(ap.parse_args(argv[1:]))
    return cmd_export(build_main_parser().parse_args(argv))


if __name__ == '__main__':
    sys.exit(main())
