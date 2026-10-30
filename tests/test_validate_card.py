#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of validate_card.py: a complete working directory passes; each of the 12 checks is named when it fails (eight sections
of the output contract, finding headings, [n] <-> bibliography, prose); header derived from the journal. The report text below is a fixture."""
import json, pathlib, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import validate_card as V   # noqa: E702

CARD = {'card_id': 'C1', 'question': 'q?', 'sources': {'S1': {'doi': '10.1/a', 'title': 'A'}},
        'claims': [{'id': 'A1', 'text': 'M reaches 71.2 %.', 'source': {'key': 'S1'}, 'location': 'Tab. 2'},
                   {'id': 'A2', 'text': 'M is evaluated on X.', 'source': {'key': 'S1'}, 'location': ''}]}
VERDICTS = {'claims': [{'id': 'A1', 'status': 'FOUND'}, {'id': 'A2', 'status': 'SOURCE-UNAVAILABLE'}]}
RESULT = {'studies': [{'id': 'doi:10.1/a', 'title': 'A', 'year': '2022', 'confidence': 0.9, 'basis': 'abstract',
                       'criteria': {k: 'x' for k in ('population', 'intervention_exposure', 'comparator', 'results', 'study_design', 'date_language_type')}}],
          'saturation': 'two empty waves', 'calls_used': 2, 'verification': {'entries_removed': 0, 'rule': 'none'}}
WORDS = ' '.join('word%d' % i for i in range(230))
COVERAGE = 'Source coverage: active: openalex, crossref; skipped: none for lack of a key; semantic-scholar not wired (S2_API_KEY absent, https://www.semanticscholar.org/product/api); suggestions: none.\n'
INTRO = '## Introduction\nQuestion q, T 2026-10-26, plugin cs-ai. Method: scoping, 3 searchers, two waves.\n'
FINDING4 = '### Finding 4 — limits\nSelf-reported figures [1]. Verdict: open.\n'
REPORT_MD = f"""# Report: q?
## Executive Summary
M reaches 71.2 % on X [1]. {WORDS}
{INTRO}## Main Analysis
### Finding 1 — M is better
The sources establish that M reaches 71.2 % [1]. Nothing contradicts it. Consequence: M dominates. Verdict: established.
### Finding 2 — M is evaluated on X
M is evaluated on X [1]. Verdict: probable.
### Finding 3 — empty angle
No replication found. Verdict: open.
{FINDING4}## Synthesis & Insights
A single document carries everything.
## Limitations & Caveats
Angle 3 searched without success.
## Recommendations
Look for replications.
## Bibliography
[1] A. Author, "A", 2022, doi:10.1/a (abstract read).
## Methodology Appendix
Process: 7 angles, 3 searchers, two empty waves, stop rule triggered.
{COVERAGE}Verification: 2 claims, 1 FOUND, 1 SOURCE-UNAVAILABLE; unverified claims: A2 [1]. Biases searched: none. Cost: 2 calls, 0 USD, 3 searchers. Annex: result.json, card.json.
"""


def folder(tmp, **mod):
    d = pathlib.Path(tmp)
    (d / 'searches').mkdir(exist_ok=True); (d / 'state').mkdir(exist_ok=True)
    for i in range(3): (d / 'searches' / f'{i}.md').write_text(f'query: search-openalex "x{i}" --n 20; received: doi:10.1/a')
    (d / 'state' / 'journal.jsonl').write_text('\n'.join(json.dumps(l) for l in [
        {'run': 'q1', 'T': '2026-10-26', 'call': 'search-openalex', 'ids': ['doi:10.1/a'], 'error': None},
        {'run': 'q1', 'T': '2026-10-26', 'call': 'read', 'ids': ['doi:10.1/a'], 'error': None}]))
    for name, obj in (('card.json', CARD), ('verdicts.json', VERDICTS), ('result.json', RESULT)):
        (d / name).write_text(json.dumps(mod.get(name, obj), ensure_ascii=False))
    (d / 'REPORT.md').write_text(mod.get('REPORT.md', REPORT_MD), encoding='utf-8')
    (d / 'run.json').write_text(json.dumps(mod.get('run.json', V.header(d))))
    return d


class Test(unittest.TestCase):
    def setUp(self): self.tmp = tempfile.TemporaryDirectory()
    def tearDown(self): self.tmp.cleanup()

    def test_ok_and_header(self):
        d = folder(self.tmp.name)
        self.assertEqual(V.problems(d), [])
        e = V.header(d)
        self.assertEqual((e['calls'], e['run'], e['T'], e['ids_seen'], e['calls_per_command']), (2, ['q1'], ['2026-10-26'], 1, {'search-openalex': 1, 'read': 1}))
        self.assertEqual(e['source'], 'state/journal.jsonl')

    def test_engine_ids_without_doi(self):
        """A source known only by an engine id (law, trials, dblp, osv...) is a valid identifier for check 2."""
        for k, v in (('celex', '31995L0046'), ('ecli', 'ECLI:EU:C:2017:632'), ('nct', 'NCT01169259'), ('dblp', 'conf/nips/X17'),
                     ('osv', 'GHSA-xxxx'), ('openreview', 'H1ewdiR5tQ'), ('zenodo', '3689089'), ('ja', 'CE/x.xml'), ('hal', 'hal-01'),
                     ('thesesfr', '2019X'), ('econbiz', '10012'), ):
            c = json.loads(json.dumps(CARD)); c['sources'] = {'S1': {k: v, 'title': 'A'}}
            with tempfile.TemporaryDirectory() as t:
                self.assertFalse([x for x in V.problems(folder(t, **{'card.json': c})) if x.startswith('2 ')], k)

    def test_identifier_misfiled_in_code_field(self):
        """Check 2 names a gateway identifier written in the `code` field (an annex template slip) and the field to use instead."""
        c = json.loads(json.dumps(CARD)); c['sources'] = {'S1': {'code': 'doi:10.1/a@local', 'title': 'A'}}
        with tempfile.TemporaryDirectory() as t:
            pb = [x for x in V.problems(folder(t, **{'card.json': c})) if x.startswith('2 ')]
        self.assertEqual(len(pb), 1); self.assertIn('field code holds a doi identifier', pb[0])
        c['sources'] = {'S1': {'code': 'src/a.py@0123abc', 'title': 'A'}}
        with tempfile.TemporaryDirectory() as t:
            self.assertFalse([x for x in V.problems(folder(t, **{'card.json': c})) if x.startswith('2 ')])

    def test_each_check(self):
        c2 = json.loads(json.dumps(CARD)); c2['claims'][1]['source'] = {'key': 'S9'}; c2['claims'][0]['text'] = 'TODO'
        d = folder(self.tmp.name, **{'card.json': c2, 'verdicts.json': {'claims': [{'id': 'A1', 'status': 'ABSENT'}, {'id': 'A2', 'status': 'WEIRD'}]},
                                    'result.json': {'studies': []}, 'REPORT.md': REPORT_MD.replace('## Synthesis & Insights\n', '## Synthesis\n').replace('unverified claims', 'other claims'),
                                    'run.json': {'calls': 5}})
        (d / 'searches' / '2.md').unlink(); (d / 'searches' / '1.md').write_text('nothing')
        pb = V.problems(d)
        for expected in ('2 source key cited but missing', "3 card.json: placeholder 'TODO'", '4 searches/: 2 file', '4 1.md: no query',
                         '5 claim A1: ABSENT not handled', "5 claim A2: unknown status 'WEIRD'", '6 REPORT.md: eight level-2 sections', "missing: ['Synthesis & Insights']",
                         '8 result.json: missing field: saturation', '9 run.json: 5 calls declared, 2 in the journal'):
            self.assertTrue(any(expected in p for p in pb), (expected, pb))
        d2 = folder(self.tmp.name, **{'REPORT.md': REPORT_MD.replace('unverified claims: A2 [1]', 'rest')})
        self.assertTrue(any(p.startswith('7 REPORT.md') for p in V.problems(d2)))
        # 6: order, executive summary, number and form of findings; 10: coverage; 11: [n]; 12: prose
        for variant, expected in ((REPORT_MD.replace(INTRO, '').replace('## Main Analysis\n', '## Main Analysis\n' + INTRO), '6 REPORT.md: eight level-2 sections'),
                                  (REPORT_MD.replace(INTRO, INTRO + '## Report Metadata\nx\n'), "extra: ['Report Metadata']"),
                                  (REPORT_MD.replace(WORDS, 'short'), 'Executive Summary of'),
                                  (REPORT_MD.replace(FINDING4, ''), 'finding(s)'),
                                  (REPORT_MD.replace('### Finding 3 — empty angle', '### Empty angle'), 'finding heading not in the form'),
                                  (REPORT_MD.replace('### Finding 3 — empty angle', '### Finding 3 - empty angle'), 'finding heading not in the form'),
                                  (REPORT_MD.replace(COVERAGE, ''), '"Source coverage" block missing'),
                                  (REPORT_MD.replace('skipped: none for lack of a key', 'rest'), 'without a "skipped" line'),
                                  (REPORT_MD.replace('active: openalex, crossref', 'rest'), 'without an "active" line'),
                                  (REPORT_MD.replace('Verdict: probable.', 'Verdict: probable [7].'), 'citations without a bibliography entry: [7]'),
                                  (REPORT_MD.replace('[1] A. Author', '[1] A. Author, "A", 2022.\n[2] B. Author'), 'never cited: [2]'),
                                  (REPORT_MD.replace('A single document carries everything.', '\n'.join('- bullet %d' % i for i in range(20))), 'prose >= 80 %')):
            pb = V.problems(folder(self.tmp.name, **{'REPORT.md': variant}))
            self.assertTrue(any(expected in p for p in pb), (expected, pb))
        for name in ('card.json', 'verdicts.json', 'REPORT.md', 'result.json', 'run.json'): (d2 / name).unlink()
        pb = V.problems(d2)
        for n in '15689': self.assertTrue(any(p.startswith(n + ' ') for p in pb), (n, pb))


    def test_editing_marker_left_by_a_two_step_edit(self):
        # a claim block of verdicts.json replaced by a bare marker line and never finished: unreadable JSON and the marker named, with its line
        d = folder(self.tmp.name)
        txt = json.dumps(VERDICTS, indent=1).replace('  {\n   "id": "A2"', 'PLACEHOLDER_X\n  {\n   "id": "A2"', 1)
        self.assertIn('PLACEHOLDER_X', txt); (d / 'verdicts.json').write_text(txt)
        pb = V.problems(d)
        self.assertTrue(any(p.startswith('3 verdicts.json line ') and "'PLACEHOLDER_X'" in p for p in pb), pb)
        self.assertTrue(any(p.startswith('5 verdicts.json: unreadable JSON (') for p in pb), pb)
        # REPORT.md: a marker left in the prose is named; the same word inside a code span (an identifier quoted by a code report) is not
        pb = V.problems(folder(self.tmp.name, **{'REPORT.md': REPORT_MD.replace('Process: 7 angles', 'Retractions: RETRACTIONS_LINE_PLACEHOLDER. Process: 7 angles')}))
        self.assertTrue(any(p.startswith('3 REPORT.md line ') and 'RETRACTIONS_LINE_PLACEHOLDER' in p for p in pb), pb)
        ok = folder(self.tmp.name, **{'REPORT.md': REPORT_MD.replace('A single document carries everything.', 'A single document carries everything; the repository defines `PLACEHOLDER_TOKEN`.')})
        self.assertEqual(V.problems(ok), [])
        # a JSON value quoting the word is not a marker
        c = json.loads(json.dumps(CARD)); c['claims'][1]['text'] = 'M replaces PLACEHOLDER_TOKEN at load time.'
        self.assertEqual([p for p in V.problems(folder(self.tmp.name, **{'card.json': c})) if p.startswith('3 ')], [])


if __name__ == '__main__':
    unittest.main()
