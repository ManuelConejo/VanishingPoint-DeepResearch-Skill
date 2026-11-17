# SPDX-License-Identifier: Apache-2.0
"""Shared helpers of the R3 tests (regression specification): an R3 baseline built from the valid_vp fixture, a fake gateway whose
journal is honest (count, ids, index_total, response digest), and three invented packing-card detector cases."""
import hashlib
import json
import stat
import sys
from pathlib import Path

from .am1_common import AM, VP, REBOUND, NOVP, load_tool, mutate, read_json, run_tool, sha, write_json  # noqa: F401
from .sandbox import register_script

HERE = Path(__file__).resolve().parent
SYNTHETIC_CARDS = HERE / 'fixtures' / 'synthetic_defect_cards'


def regression_text(n):
    """Three invented detector cases with intentional rendering defects.

    Case 2 combines a full synthetic packing card with a synthetic assumed
    outcome heading. These exercise detectors, not historical provenance.
    """
    excerpt = (SYNTHETIC_CARDS / ('r3-defect-excerpts-%d.card' % n)).read_text(encoding='utf-8')
    if n == 2:
        excerpt = (SYNTHETIC_CARDS / 'synthetic-packing-defects.card').read_text(encoding='utf-8') + '\n' + excerpt
    return excerpt

# the fake gateway of the AM1 tests, but its journal says what a faithful VP journal says: the number of results, their
# ids, the index total and the SHA-256 of the answer, according to the "__journal__" key of the canned file.
HONEST_GATEWAY = r'''#!/usr/bin/env python3
import hashlib, json, sys
from pathlib import Path
here = Path(__file__).resolve().parent
a = sys.argv[1:]
opts, pos, i = {}, [], 0
while i < len(a):
    if a[i] in ('--plugin', '--T', '--run', '--state', '--n', '--since', '--repo', '--language', '--path', '--ecosystem'):
        opts.setdefault(a[i], []).append(a[i + 1]); i += 2
    else:
        pos.append(a[i]); i += 1
cmd, arg = pos[0], ' '.join(pos[1:])
canned = json.loads((here / 'canned.json').read_text(encoding='utf-8'))
fields = canned.get('__journal__', {})
T = opts.get('--T', [''])[0]
key = None
for k in (cmd + '|' + arg + '|' + T, cmd + '|' + arg, cmd + '|*|' + T, cmd + '|*', cmd):
    if k in canned:
        key = k; break
state = Path(opts.get('--state', ['state'])[0]); state.mkdir(parents=True, exist_ok=True)
with open(str(here / 'calls.jsonl'), 'a') as f:
    f.write(json.dumps({'argv': a}) + '\n')
if key is None:
    print(json.dumps({'refusal': 'nothing canned for ' + cmd})); sys.exit(0)
out = dict(canned[key]); out.setdefault('query', arg); out.setdefault('bound', 'documents before ' + T)
res = out.get('results')
items = res.get('repos') if isinstance(res, dict) and 'repos' in res else (res if isinstance(res, list) else ([res] if res else []))
entry = {'utc': '2026-11-14T10:00:00+00:00', 'run': opts.get('--run', ['vp'])[0], 'T': T, 'call': cmd, 'engine': None,
         'query': arg, 'n': 20, 'count': len(items), 'excluded': 0, 'error': None, 'ids': []}
if fields.get('total'):
    entry['index_total'] = out.get('index_total')
if fields.get('digest'):
    entry['response_sha256'] = hashlib.sha256(json.dumps(out, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
with open(str(state / 'journal.jsonl'), 'a') as f:
    f.write(json.dumps(entry) + '\n')
print(json.dumps(out))
'''

def fr(s):
    """French test text without accented letters in the source (tests/test_docs.py): {e'} {e`} {a`} {o^} {x} stand for the
    accented letters and the multiplication sign."""
    for k, v in (("{e'}", 0xe9), ("{e`}", 0xe8), ("{a`}", 0xe0), ("{o^}", 0xf4), ("{x}", 0xd7)):
        s = s.replace(k, chr(v))
    return s


LONG600 =' '.join('word%03d' % i for i in range(75))      # 600 characters, no sentence end


def second_raw(work, text):
    p = Path(work) / 'critique2-raw.txt'
    p.write_text(text, encoding='utf-8')
    return p.name, hashlib.sha256(p.read_bytes()).hexdigest()


RAW2 = ("Item 0: the positive control now drops the query term, so sensitivity to titles is shown; objection lifted. "
        "Item 1: the L0 control with titles alone is written; objection lifted.")


class R3(AM):
    """AM with an R3 baseline: to_r3() upgrades a copy of valid_vp (or valid_vp_rebound) to a directory that passes."""

    def setUp(self):
        super().setUp()
        self.sim = load_tool('sim')
        self.r3 = load_tool('r3check')
        self.guards = load_tool('guards')

    def vp_fake(self, canned=None, digest=False, total=False):
        vp = self.tmp / 'fakevp'
        (vp / 'tools').mkdir(parents=True, exist_ok=True)
        (vp / 'SKILL.md').write_text('---\nname: vanishingpoint\ndescription: fake\n---\n', encoding='utf-8')
        g = vp / 'tools' / 'gateway.py'
        g.write_text(HONEST_GATEWAY.replace('#!/usr/bin/env python3', '#!' + sys.executable), encoding='utf-8')
        g.chmod(g.stat().st_mode | stat.S_IXUSR)
        register_script(g)
        c = dict(canned or {})
        c['__journal__'] = {'digest': digest, 'total': total}
        write_json(vp / 'tools' / 'canned.json', c)
        return vp

    def to_r3(self, name=VP):
        w = self.work(name)
        if read_json(w / 'intake.json').get('frontier_version') == 3:
            return w                                   # idempotent: a test may call it again after fresh()

        def intake(d):
            d['frontier_version'] = 3
            d['query_terms'] = ['title', 'retrieval', 'citations', 'ranking']
        mutate(w, 'intake.json', intake)

        def tests(d):
            for t in d['tests']:
                t['traps']['data_split']['data_seen_before'] = (
                    'The pilot alone informed the frozen rule; confirmation records remain unseen.')
                t['verdict_scope'] = {
                    'concludes_about': 'the observed association in these records under the frozen comparison',
                    'does_not_conclude_about': ['unexamined fields, alternative search services or reader behaviour']}
                t['sensitivity']['power'] = {
                    'role': 'protocol_support',
                    'target_metric': 'the primary paired contrast between the two title variants',
                    'metric_is_target': True,
                    'costs': 'no transaction cost: the outcome is a rank or a ratio, not a return',
                    'data_available': 'public metadata dump; no data of the user was given (idea alone)',
                    'prior_trials': 'none known to the author; the closest works are in prior_art.json',
                    'parameters': [
                        {'name': 'n', 'status': 'assumed', 'low': 150, 'central': 200 if t['id'] == 'T1' else 2000, 'high': 250},
                        {'name': 'sd', 'status': 'assumed', 'low': 4, 'central': 5, 'high': 7}],
                    'model': {'dependence': 'records are independent draws; a small AR(1) is simulated as a stress',
                              'overlap': 'no overlapping observations (one query per record)',
                              'justification': 'paired rank differences on distinct records are close to independent; the stress covers drift'}}
                if 'simulation' not in t['sensitivity']:
                    t['sensitivity']['power'].pop('parameters')
                    t['sensitivity']['power']['parameters'] = [{'name': 'n', 'status': 'assumed', 'low': 1000, 'central': 2000, 'high': 2500}]
                    t['sensitivity']['power']['not_applicable_why'] = 'overdispersed counts: the permutation null plays the role of the simulation'
        mutate(w, 'tests.json', tests)
        r = run_tool('sim', 'robust', '--design', 'paired', '--tests', w / 'tests.json', '--test', 'T1',
                     '--useful-effect', '3', '--rho', '0,0.3,0.6', '--overlap', '1', '--reps', '60')
        assert r.returncode == 0, r.stdout + r.stderr
        raw, digest = second_raw(w, RAW2)

        def crit(d):
            d['items'][0]['response']['proof'] = {
                'kind': 'tests_diff', 'where': 'tests.T1.traps.positive_control.description',
                'evidence': 'Records whose shortened title drops the query term must lose rank',
                'addresses': 'the index must be shown sensitive to titles: positive control on titles'}
            d['items'][1]['response']['proof'] = {
                'kind': 'tests_diff', 'where': 'tests.T2.l0_leakage_control.description',
                'evidence': 'must not predict citation rank above chance',
                'addresses': 'a rating of title clarity may know which papers became famous: L0 control'}
            d['second_critique'] = {
                'route': 'subagent', 'critic_family': 'openai', 'raw_output': raw, 'raw_sha256': digest,
                'verdicts': [{'item': 0, 'objection_lifted': 'yes', 'why': 'the positive control now drops the query term'},
                             {'item': 1, 'objection_lifted': 'yes', 'why': 'the L0 control with titles alone is written'}]}
        mutate(w, 'critique.json', crit)

        def run(d):
            d['steps'].append({'step': 'critique2', 'utc': '2026-11-14T10:40:00Z', 'duration_s': 'unknown', 'cost_usd': 0})
        mutate(w, 'run.json', run)

        def reco(d):
            d['tomorrow'] = {'test': 'T1', 'first_action': 'Freeze the title-editing rule, index 200 records, and only then run the query set.'}
            d['justification'] = {'from': ['K1'], 'link': 'K1 shows the association exists, T1 shows the retrieval lever works under control.'}
        mutate(w, 'recommendation.json', reco)
        write_json(w / 'decisive_claims.json', {'claims': [{
            'id': 'K1', 'decides': 'prior_art', 'claim': 'Shorter titles are associated with more citations in several fields',
            'ref': {'id': 'doi:10.1000/titles.2019', 'run': 'prior_art', 'claim': 'A1'},
            'fragment': 'shorter titles received more citations', 'supports': 'full',
            'scope': 'an observed association in the abstract of that study',
            'limits': 'no causal claim, no retrieval mechanism, fields not named in the abstract',
            'why_linked': 'the fragment states the association that the idea takes as its starting point'}]})
        run_tool('guards', 'coverage-write', w)
        return w

    def code_in(self, code, probs):
        return any(p.startswith(code) for p in probs)

    def assertR3Clean(self, name=VP):
        p = self.probs(name)
        self.assertEqual([x for x in p if not x.startswith('[CARD')], [], p)
