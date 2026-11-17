# SPDX-License-Identifier: Apache-2.0
"""Shared helpers of the AM1 tests (regression specification): a fake VP directory whose gateway is a script that answers from a
canned file (no network, no model), a free draft with the claims that cover it, small project folders."""
import hashlib
import json
import stat
import sys
from pathlib import Path

from .helpers import TempCase, load_tool, mutate, read_json, run_tool, write_json
from .sandbox import register_script

VP = 'valid_vp'
NOVP = 'valid_novp'
REBOUND = 'valid_vp_rebound'

DRAFT = (
    "Synthetic workshop and reference names. Working notes before any search. Shorter titles may help retrieval in scholarly search engines. "
    "Close work I remember: Feltwick et al. (2022) found felt sleeves beat paper cradles on painted wooden tiles. "
    "Also (Smith et al., 2019) reported a citation gain of 12.5% for titles under ten words. "
    "The padding ratio of 1,82 quoted for the cradle looks fragile and the standard error is about 0.27 with eighty-four "
    "observations. Neighbouring idea: washable corner inserts. See also doi:10.1000/titles.2019 for the association.\n")

Q_SLEEVE = "Feltwick et al. (2022) found felt sleeves beat paper cradles on painted wooden tiles"
Q_SMITH = "(Smith et al., 2019) reported a citation gain of 12.5% for titles under ten words"
Q_PADDING = ("The padding ratio of 1,82 quoted for the cradle looks fragile and the standard error is about 0.27 "
            "with eighty-four observations")
Q_DOI = "See also doi:10.1000/titles.2019 for the association"

GOOD_REF = {"id": "doi:10.1000/titles.2019", "run": "prior_art", "claim": "A1"}

FAKE_GATEWAY = r'''#!/usr/bin/env python3
import json
import sys
from pathlib import Path
here = Path(__file__).resolve().parent
a = sys.argv[1:]
opts, pos, i = {}, [], 0
while i < len(a):
    if a[i] in ('--plugin', '--T', '--run', '--state', '--n', '--since', '--repo', '--language', '--path', '--ecosystem'):
        opts.setdefault(a[i], []).append(a[i + 1])
        i += 2
    else:
        pos.append(a[i])
        i += 1
cmd = pos[0]
arg = ' '.join(pos[1:])
canned = json.loads((here / 'canned.json').read_text(encoding='utf-8'))
T = opts.get('--T', [''])[0]
key = None
for k in (cmd + '|' + arg + '|' + T, cmd + '|' + arg, cmd + '|*|' + T, cmd + '|*', cmd):
    if k in canned:
        key = k
        break
state = Path(opts.get('--state', ['state'])[0])
state.mkdir(parents=True, exist_ok=True)
with open(str(here / 'calls.jsonl'), 'a') as f:
    f.write(json.dumps({'argv': a}) + '\n')
if key is None:
    out = {'refusal': 'fake gateway: nothing canned for ' + cmd}
else:
    out = dict(canned[key])
    out.setdefault('query', arg)
    out.setdefault('bound', 'documents before ' + T)
with open(str(state / 'journal.jsonl'), 'a') as f:
    f.write(json.dumps({'utc': '2026-11-14T10:00:00+00:00', 'run': opts.get('--run', ['vp'])[0], 'T': T, 'call': cmd,
                        'engine': None, 'query': arg, 'n': 20, 'count': 1, 'excluded': 0, 'error': None,
                        'ids': []}) + '\n')
print(json.dumps(out))
'''

REPO_INFO = {"index_total": None, "results": {
    "id": "repo:owner/name", "licence": "MIT", "archived": False, "pushed_at": "2026-12-01T00:00:00Z",
    "at_T": {"sha": "abc123", "date": "2026-03-02", "licence": "MIT"}}}
FIND_IMPL = {"index_total": None, "results": {"repos": [
    {"repo": "owner/name", "stars": 120, "file": "repo:owner/name/src/x.py:1-20@abc"}, {"repo": "other/lib", "stars": 5}]}}
HF_DATA = {"index_total": 1, "results": [
    {"id": "hfdataset:synthetic/tiles", "title": "Synthetic tile inspection panel", "date": "2025-02-01", "licence": "cc-by-4.0"}]}


def totals_for(totals, as_ofs, key='search-openalex|*|'):
    return {key + d: {"index_total": t, "results": []} for d, t in zip(as_ofs, totals)}


AS_OFS = ['2021-11-14', '2022-11-14', '2023-11-14', '2024-11-14', '2025-11-14', '2026-11-14']
RISING = [1000, 1100, 1250, 1450, 1750, 2200]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class AM(TempCase):
    def setUp(self):
        super().setUp()
        self.check = load_tool('check')

    # ---- check helpers
    def probs(self, name=VP):
        return self.check.problems(self.work(name))

    def assertCode(self, code, name=VP):
        p = self.probs(name)
        self.assertTrue(any(x.startswith(code) for x in p), '%s not in %r' % (code, p))
        return p

    def assertNoCode(self, code, name=VP):
        p = self.probs(name)
        self.assertFalse(any(x.startswith(code) for x in p), '%s in %r' % (code, p))

    def assertClean(self, name=VP):
        self.assertEqual(self.probs(name), [])

    def mut(self, name, fname, fn):
        mutate(self.work(name), fname, fn)

    def card(self, name=VP):
        return run_tool('card', self.work(name))

    # ---- draft
    def add_draft(self, name=VP, claims=None, draft=DRAFT, step=True, claims_file=True):
        w = self.work(name)
        (w / 'free_draft.md').write_text(draft, encoding='utf-8')
        if claims_file:
            if claims is None:
                claims = [
                    {"id": "D1", "quote": Q_SLEEVE, "status": "verified", "ref": dict(GOOD_REF)},
                    {"id": "D2", "quote": Q_SMITH, "status": "unverified_memory"},
                    {"id": "D3", "quote": Q_PADDING, "status": "unverified_memory"},
                    {"id": "D4", "quote": Q_DOI, "status": "verified", "ref": dict(GOOD_REF)}]
                if name == NOVP:
                    for c in claims:
                        c['status'] = 'unverified_memory'
                        c.pop('ref', None)
            write_json(w / 'draft_claims.json', {"draft_sha256": sha(w / 'free_draft.md'), "claims": claims})
        if step:
            def go(d):
                d['steps'].insert(0, {"step": "free_draft", "utc": "2026-11-14T08:50:00Z", "duration_s": "unknown",
                                      "cost_usd": "unknown", "sha256": sha(w / 'free_draft.md')})
            mutate(w, 'run.json', go)
        return w

    # ---- fake VP
    def fake_vp(self, canned):
        vp = self.tmp / 'fakevp'
        (vp / 'tools').mkdir(parents=True, exist_ok=True)
        (vp / 'SKILL.md').write_text('---\nname: vanishingpoint\ndescription: fake\n---\n', encoding='utf-8')
        g = vp / 'tools' / 'gateway.py'
        g.write_text(FAKE_GATEWAY.replace('#!/usr/bin/env python3', '#!' + sys.executable), encoding='utf-8')
        g.chmod(g.stat().st_mode | stat.S_IXUSR)
        register_script(g)
        write_json(vp / 'tools' / 'canned.json', canned)
        return vp

    def fake_calls(self):
        p = self.tmp / 'fakevp' / 'tools' / 'calls.jsonl'
        if not p.exists():
            return []
        return [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]

    # ---- project folder
    def project(self):
        root = self.tmp / 'proj'
        (root / 'results').mkdir(parents=True, exist_ok=True)
        (root / 'lessons').mkdir(parents=True, exist_ok=True)
        (root / 'README.md').write_text(
            "# Synthetic tile inspection scores\n"
            "We inspect painted tiles over 60 periods (15 years).\n"
            "Workshop: n = 2300 tiles.\n"
            "Synthetic rank-IC: 0.046 on the masked inspection set.\n"
            "Handling cost: 17 bps of the invented workshop budget.\n"
            "Synthetic diagnostic named Sharpe 2.41 for tile scores.\n", encoding='utf-8')
        (root / 'results' / 'results-2026-q3.md').write_text(
            "# Results\nSynthetic diagnostic sharpe 0.93 over 48 quarters of tile inspection.\n", encoding='utf-8')
        (root / 'lessons' / 'LESSONS.md').write_text(
            "# Lessons\nRepeated handling cost: 23 bps per quarter of workshop practice.\n", encoding='utf-8')
        (root / 'notes.md').write_text("Unrelated file with 999 tiles and 77 periods.\n", encoding='utf-8')
        return root

    def set_intake(self, name, fn):
        mutate(self.work(name), 'intake.json', fn)
