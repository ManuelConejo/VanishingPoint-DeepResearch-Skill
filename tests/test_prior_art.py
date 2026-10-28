#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of the optional "Prior art?" mode (tools/prior_art.py, validate_card.py --prior-art, finish_run.py --prior-art), on
recorded verdicts (no gateway call, no model): EXISTS only when one source discloses every element with FOUND claims; PARTIALLY for a
combination or a subset; NOT FOUND states what was searched (engines, queries, the denominator, patents not searched) from the journal;
DISTORTED, SOURCE-UNAVAILABLE and UNVERIFIED never count as disclosed, and the answer says when the unverified ones would change it;
PENDING without verdicts.json; closest prior art ranked by elements disclosed; the checks refuse a bad prior_art.json, a claim on an
unknown element, a stale or hand-edited PRIOR-ART.md, a NOT FOUND without a recorded search; the mode is off unless asked for."""
import contextlib, io, json, pathlib, shutil, subprocess, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
TOOLS = P.parent / 'tools'
sys.path.insert(0, str(TOOLS))
import prior_art as PA   # noqa: E402
import validate_card as VC   # noqa: E402
import finish_run as F   # noqa: E402

SPEC = {'idea': 'A <b>gated</b> retriever that re-ranks with a small verifier', 'T': '2024-01-01',
        'elements': [{'id': 'E1', 'text': 'retrieval gated by a confidence score'}, {'id': 'E2', 'text': 're-ranking by a small verifier model'}]}
JOURNAL = [{'call': 'search-openalex', 'engine': 'openalex', 'query': 'gated retrieval verifier rerank', 'ids': ['doi:10.1/a', 'arxiv:2301.00001'], 'excluded': 1, 'T': '2024-01-01'},
           {'call': 'search-arxiv', 'engine': 'arxiv', 'query': 'confidence gated RAG', 'ids': ['arxiv:2301.00001', 'arxiv:2302.00002'], 'excluded': 0, 'T': '2024-01-01'},
           {'call': 'citing', 'engine': None, 'query': 'doi:10.1/a', 'ids': ['doi:10.1/b'], 'excluded': 0, 'T': '2024-01-01'},
           {'call': 'read', 'query': 'doi:10.1/a', 'ids': ['doi:10.1/a'], 'T': '2024-01-01'},
           {'call': 'read', 'query': 'arxiv:2301.00001', 'ids': ['arxiv:2301.00001'], 'pool': 'verifier', 'T': '2024-01-01'}]
SOURCES = {'S1': {'doi': '10.1/a', 'title': 'Gated retrieval', 'year': '2021'}, 'S2': {'arxiv': '2301.00001', 'title': 'Verifier re-ranking', 'year': '2023'},
           'S3': {'arxiv': '2302.00002', 'title': 'Older full system', 'year': '2019'}}


def make(d, links, statuses, journal=True, verdicts=True):
    """links: [(claim id, source key, element)]; statuses: {claim id: status}."""
    (d / 'searches').mkdir(parents=True)
    for n in (1, 2, 3): (d / 'searches' / f'{n}.md').write_text(f'# searches/{n}.md\nReceipts: search-openalex "gated retrieval"\n')
    if journal:
        (d / 'state').mkdir(); (d / 'state' / 'journal.jsonl').write_text('\n'.join(json.dumps(e) for e in JOURNAL) + '\n')
    (d / 'prior_art.json').write_text(json.dumps(SPEC))
    keys = sorted({k for _, k, _ in links})
    (d / 'card.json').write_text(json.dumps({'card_id': 'pa', 'question': 'Prior art? ' + SPEC['idea'], 'sources': {k: SOURCES[k] for k in keys},
                                             'claims': [{'id': i, 'text': f'{k} discloses {e}', 'source': {'key': k}, 'location': 'abstract', 'element': e} for i, k, e in links]}))
    if verdicts:
        (d / 'verdicts.json').write_text(json.dumps({'claims': [{'id': i, 'status': statuses[i], 'discrepancy': '' if statuses[i] == 'FOUND' else f'{i}: scope differs',
                                                                 'fragments': [f'fragment of {i}'] if statuses[i] in ('FOUND', 'DISTORTED') else []} for i, _, _ in links]}))


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_dir(self, name, links, statuses, **kw):
        d = self.tmp / name; make(d, links, statuses, **kw); return d

    def test_exists(self):
        d = self.run_dir('ex', [('A1', 'S1', 'E1'), ('A2', 'S2', 'E2'), ('A3', 'S3', 'E1'), ('A4', 'S3', 'E2')], {'A1': 'FOUND', 'A2': 'FOUND', 'A3': 'FOUND', 'A4': 'FOUND'})
        x = PA.decide(d)
        self.assertEqual((x['answer'], x['exists_in'], x['could_be']), ('EXISTS', ['S3'], None))
        self.assertEqual(x['closest'][0]['key'], 'S3')                         # all elements first, then earliest year
        md = PA.render(x)
        self.assertIn('**Exists** as of 2024-01-01: [3] discloses every element (E1, E2), each claim verified FOUND.', md)
        self.assertIn('- [3]: nothing; it discloses every element.', md)

    def test_partially_combination_and_distorted(self):
        d = self.run_dir('pa', [('A1', 'S1', 'E1'), ('A2', 'S2', 'E2'), ('A3', 'S2', 'E1')], {'A1': 'FOUND', 'A2': 'FOUND', 'A3': 'DISTORTED'})
        x = PA.decide(d)
        self.assertEqual(x['answer'], 'PARTIALLY'); self.assertEqual(x['novel_elements'], [])
        self.assertEqual(x['coverage'][0], {'element': 'E1', 'disclosed_by': ['S1'], 'other': [('S2', 'DISTORTED')]})
        md = PA.render(x)
        self.assertIn('each element is disclosed somewhere, never all in one source', md)
        self.assertIn('E1 DISTORTED (A3: scope differs)', md)

    def test_unverified_could_change(self):
        d = self.run_dir('un', [('A1', 'S3', 'E1'), ('A2', 'S3', 'E2')], {'A1': 'FOUND', 'A2': 'SOURCE-UNAVAILABLE'})
        x = PA.decide(d)
        self.assertEqual((x['answer'], x['could_be']), ('PARTIALLY', 'EXISTS'))
        self.assertIn('Could be **Exists** if the unverified claim(s) A2 were confirmed', PA.render(x))
        d2 = self.run_dir('un2', [('A1', 'S3', 'E1')], {'A1': 'UNVERIFIED'})
        x = PA.decide(d2); self.assertEqual((x['answer'], x['could_be']), ('NOT FOUND', 'PARTIALLY'))

    def test_not_found_states_the_search(self):
        d = self.run_dir('nf', [], {})
        x = PA.decide(d); md = PA.render(x)
        self.assertEqual(x['answer'], 'NOT FOUND')
        self.assertIn('no element of the idea is disclosed by a verified claim among the 4 distinct records returned by 3 searches and the 1 documents read', md)
        self.assertIn('Not found is not proof of absence', md)
        self.assertIn('`search-openalex` "gated retrieval verifier rerank": 2 records, 1 after T', md)
        self.assertIn('`citing` "doi:10.1/a": 1 records', md)
        self.assertIn('arxiv (1 calls, 2 records)', md)
        self.assertIn('patents: not searched: no patent source is wired in the gateway', md)
        self.assertIn('code: not searched', md)
        self.assertIn('1 documents were read', md)                       # the verifier pool's read is not counted

    def test_pending_and_checks(self):
        d = self.run_dir('pe', [('A1', 'S1', 'E1')], {'A1': 'FOUND'}, verdicts=False)
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(PA.main([str(d)]), 0)
        self.assertTrue((d / 'PRIOR-ART.md').read_text().startswith('<!-- prior_art.py inputs sha256:'))
        self.assertIn('**Pending verification**', (d / 'PRIOR-ART.md').read_text())
        pb = VC.problems(d, prior_art=True)
        self.assertTrue(any(p.startswith('PA3 answer pending') for p in pb)); self.assertTrue(any(p.startswith('5 verdicts.json: missing') for p in pb))

    def test_validate_and_finish(self):
        d = self.run_dir('ok', [('A1', 'S1', 'E1'), ('A2', 'S1', 'E2')], {'A1': 'FOUND', 'A2': 'FOUND'})
        self.assertIn('PA3 PRIOR-ART.md missing: run python3 -I tools/prior_art.py <dir>', VC.problems(d, prior_art=True))
        fetch = F.gw.fetch; F.gw.fetch = lambda *a, **k: (_ for _ in ()).throw(OSError('offline test'))
        try: r = F.finish(d, offline=True, prior_art=True)
        finally: F.gw.fetch = fetch
        st = [(s['step'], s['status']) for s in r['steps']]
        self.assertEqual(st[:3], [('prior_art', 'ok'), ('validate_card --header', 'ok'), ('validate_result', 'skipped')], r['steps'])
        self.assertTrue(r['validation_passed'])
        cli = subprocess.run([sys.executable, '-I', str(TOOLS / 'validate_card.py'), str(d), '--prior-art'], capture_output=True, text=True)
        self.assertEqual((cli.returncode, cli.stdout.strip()), (0, 'OK'))
        # off by default: the same directory is not a deliverable standard run
        self.assertTrue(any(p.startswith('6 REPORT.md: missing') for p in VC.problems(d)))
        # a hand edit of the answer is refused, and so is a change of the verdicts after the answer
        p = d / 'PRIOR-ART.md'; t = p.read_text()
        p.write_text(t.replace('answer:EXISTS', 'answer:NOT FOUND', 1))
        self.assertTrue(any('differs from the answer of the files' in x for x in VC.problems(d, prior_art=True)))
        p.write_text(t); self.assertEqual(VC.problems(d, prior_art=True), [])
        v = json.loads((d / 'verdicts.json').read_text()); v['claims'][1]['status'] = 'DISTORTED'; (d / 'verdicts.json').write_text(json.dumps(v))
        pb = VC.problems(d, prior_art=True) + VC.end_problems(d)
        self.assertTrue(any(x.startswith('PA3 PRIOR-ART.md stale') for x in pb)); self.assertTrue(any(x.startswith('13 end steps stale') for x in pb))

    def test_spec_and_claim_checks(self):
        d = self.run_dir('bad', [('A1', 'S1', 'E9')], {'A1': 'FOUND'})
        with contextlib.redirect_stdout(io.StringIO()): PA.main([str(d)])
        self.assertIn("PA2 claim A1: \"element\" 'E9' not among ['E1', 'E2']", VC.problems(d, prior_art=True))
        self.assertEqual(PA.spec_problems({'idea': '', 'elements': [{'id': 'X', 'text': ''}, {'id': 'X', 'text': 'a'}]}),
                         ['PA1 prior_art.json: empty "idea"', "PA1 prior_art.json: element {'id': 'X', 'text': ''} needs \"id\" E<k> and a non-empty \"text\"",
                          "PA1 prior_art.json: element {'id': 'X', 'text': 'a'} needs \"id\" E<k> and a non-empty \"text\"", 'PA1 prior_art.json: duplicate element ids'])
        many = {'idea': 'x', 'elements': [{'id': f'E{i}', 'text': 't'} for i in range(PA.CFG['elements_max'] + 1)]}
        self.assertTrue(PA.spec_problems(many)[0].startswith('PA1 prior_art.json: 9 elements'))
        (d / 'prior_art.json').write_text('{')
        with contextlib.redirect_stdout(io.StringIO()) as o: self.assertEqual(PA.main([str(d)]), 1)
        self.assertIn('PA1 prior_art.json: missing or unreadable JSON', o.getvalue())

    def test_not_found_without_search(self):
        d = self.run_dir('ns', [], {}, journal=False)
        with contextlib.redirect_stdout(io.StringIO()): PA.main([str(d)])
        self.assertIn('Not recorded: no state/journal.jsonl', (d / 'PRIOR-ART.md').read_text())
        self.assertIn('PA4 NOT FOUND without any search recorded in state/journal.jsonl', VC.problems(d, prior_art=True))


if __name__ == '__main__':
    unittest.main()
