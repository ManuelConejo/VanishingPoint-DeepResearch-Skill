#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline tests of tools/read_candidates.py (free batch reading of the candidates left possible/probable on title, SKILL.md section 4 step 7)
and of the borderline flag of result.json (validate_result.py). No network: the gateway's fetch, jget and pubmed_summ are replaced."""
import json, pathlib, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import gateway as gw            # noqa: E402
import read_candidates as R      # noqa: E402
import validate_result as V     # noqa: E402

SEARCH1 = """# Search 1
## Candidates
- pmid:111 | Title one randomised | 2010 | title says "randomised" | title | possible
- pmid:222 | Title two | 2011 | METHODS "randomly assigned" | abstract | probable
- pmid:333 | Title three | 2012 | design not seen | basis title | excluded (cohort)
- doi:10.1000/ABC.9. | Title four | 2009 | title only | title | probable
Observational/other: pmid:444 (possible follow-up of an RCT), pmid:555
"""
SEARCH2 = """# Search 2
- pmid:666 | Title six | 2015 | title | possible (low)
- pmid:777 | Title seven | 2016 | title | possible
"""
EFETCH = b"""<?xml version="1.0"?><PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID>111</PMID><Article><Abstract><AbstractText Label="METHODS">Patients were randomly allocated.</AbstractText>
<AbstractText Label="RESULTS">Fewer complications.</AbstractText></Abstract><PublicationTypeList><PublicationType>Randomized Controlled Trial</PublicationType>
</PublicationTypeList></Article></MedlineCitation></PubmedArticle>
<PubmedArticle><MedlineCitation><PMID>444</PMID><Article><Abstract><AbstractText>Follow-up of a trial.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle>
<PubmedArticle><MedlineCitation><PMID>555</PMID><Article></Article></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)
        (self.d / 'searches').mkdir(); (self.d / 'state').mkdir()
        (self.d / 'searches' / '1.md').write_text(SEARCH1); (self.d / 'searches' / '2.md').write_text(SEARCH2)
        # pmid:777 already read through the gateway (search pool): not read again
        (self.d / 'state' / 'journal.jsonl').write_text(json.dumps({'run': 'r', 'call': 'read', 'query': 'pmid:777', 'ids': ['pmid:777'], 'error': None}) + '\n')
        self.calls = []
        self.saved = {k: getattr(gw, k) for k in ('fetch', 'jget', 'pubmed_summ', 'read_arxiv')}

        def summ(ids, B):   # 666 is dated after T: refused by the barrier
            self.calls.append(('esummary', list(ids)))
            return [{'id': f'pmid:{i}', 'doi': '10.1000/abc.9' if i == '111' else None, 'title': f'T{i}', 'year': '2010'} for i in ids if i != '666']

        def fetch(url, headers=None):
            self.calls.append(('efetch', url)); return EFETCH

        def jget(url):
            self.calls.append(('epmc', url)); return {'resultList': {'result': []}}
        gw.pubmed_summ, gw.fetch, gw.jget = summ, fetch, jget

    def tearDown(self):
        for k, v in self.saved.items(): setattr(gw, k, v)
        self.tmp.cleanup()


class Candidates(Base):
    def test_batch_receipts_do_not_classify_candidates_as_read(self):
        state = self.d / 'state'
        with (state / 'journal.jsonl').open('a') as stream:
            for pool, engine, ident in [('possibles', 'read_possibles', 'pmid:111'),
                                        ('candidate_reading', 'read_candidates', 'pmid:666')]:
                stream.write(json.dumps({'pool': pool, 'engine': engine, 'call': 'read-batch',
                                         'ids': [ident], 'error': None}) + '\n')
        ids, _ = R.candidates(self.d, state)
        self.assertIn('pmid:111', ids)
        self.assertIn('pmid:666', ids)

    def test_title_only_possible_or_probable(self):
        ids, c = R.candidates(self.d, self.d / 'state')
        # 222 read on abstract, 333 excluded, 777 read in the journal; the DOI is normalised; ids of a free-text line are taken
        self.assertEqual(ids, ['pmid:111', 'doi:10.1000/abc.9', 'pmid:444', 'pmid:555', 'pmid:666'])
        self.assertEqual((c['listed'], c['already_read']), (7, 2))

    def test_max_records_from_config(self):
        old = R.CFG['max_records']; R.CFG['max_records'] = 2
        try:
            ids, c = R.candidates(self.d, self.d / 'state')
            self.assertEqual((len(ids), c['over_max_records']), (2, 3))
        finally: R.CFG['max_records'] = old


    def test_doi_with_balanced_parentheses(self):
        # Lancet-style DOIs keep their parentheses; a DOI inside parentheses loses the closing one
        (self.d / 'searches' / '1.md').write_text('- doi:10.1016/S0140-6736(05)67889-0 | t | 2005 | title | possible\n'
                                                  '- Trial X (doi:10.1000/xyz.1) | 2001 | title | probable\n')
        (self.d / 'searches' / '2.md').write_text('')
        ids, _ = R.candidates(self.d, self.d / 'state')
        self.assertEqual(ids, ['doi:10.1016/s0140-6736(05)67889-0', 'doi:10.1000/xyz.1'])


class InputAliases(Base):
    def test_config_fallback_and_precedence(self):
        import contextlib, io
        old = dict(R.CFG, max_records=17, journal_pool='possibles')
        for cfg, count, warning in [({'possibles': old}, 17, True),
                                    ({'possibles': old, 'candidate_reading': R.CFG}, R.CFG['max_records'], True)]:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                result = R.read_config(cfg)
            self.assertEqual(result['max_records'], count)
            self.assertEqual(result['journal_pool'], 'candidate_reading')
            self.assertEqual('deprecated name, use candidate_reading' in err.getvalue(), warning)

    def test_saved_reading_never_combines_generations(self):
        import itertools, subprocess
        state = self.d / 'state'
        paths = [state / (stem + suffix) for stem in ('candidate_reading', 'possibles') for suffix in ('.md', '.json')]
        for exists in itertools.product((False, True), repeat=4):
            with self.subTest(exists=exists):
                for index, (path, present) in enumerate(zip(paths, exists)):
                    if path.exists():
                        path.unlink()
                    if present:
                        path.write_text(('new' if index < 2 else 'old') if path.suffix == '.md' else ('{"served": 4}' if index < 2 else '{"served": 3}'))
                before = {p.name: p.read_bytes() for p in paths if p.exists()}
                if all(exists[:2]):
                    self.assertEqual(R.load_reading(state), {'markdown': 'new', 'summary': {'served': 4}})
                elif not any(exists[:2]) and all(exists[2:]):
                    self.assertEqual(R.load_reading(state), {'markdown': 'old', 'summary': {'served': 3}})
                else:
                    with self.assertRaisesRegex(ValueError, 'pair|saved'):
                        R.load_reading(state)
                    result = subprocess.run([sys.executable, '-I', str(P.parent / 'tools' / 'read_candidates.py'),
                                             '--state', str(state), '--show'], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertEqual(result.stdout, '')
                    self.assertRegex(result.stderr, 'pair|saved')
                self.assertEqual({p.name: p.read_bytes() for p in paths if p.exists()}, before)

    def test_legacy_config_at_import_and_through_saturation(self):
        import shutil, subprocess
        copied = self.d / 'tools'
        shutil.copytree(P.parent / 'tools', copied, ignore=shutil.ignore_patterns('__pycache__'))
        config = json.loads((copied / 'config.json').read_text())
        config['possibles'] = config.pop('candidate_reading')
        config['possibles'].update(max_records=0, journal_pool='possibles')
        (copied / 'config.json').write_text(json.dumps(config))
        result = subprocess.run([sys.executable, '-I', str(copied / 'read_candidates.py'), '--dir', str(self.d),
                                 '--state', str(self.d / 'state'), '--T', '2020-01-01', '--run', 'r'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('deprecated name, use candidate_reading', result.stderr)
        saved = json.loads((self.d / 'state' / 'candidate_reading.json').read_text())
        self.assertEqual(saved['to_read'], 0)
        self.assertGreater(saved['over_max_records'], 0)
        result = subprocess.run([sys.executable, '-I', str(copied / 'saturation.py'), '--dir', str(self.d)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('deprecated name, use candidate_reading', result.stderr)

    def test_saved_legacy_reading_cli_and_new_precedence(self):
        import subprocess
        state = self.d / 'state'
        (state / 'possibles.md').write_text('# Abstracts (tools/read_possibles.py)\nold abstract\n')
        (state / 'possibles.json').write_text('{"served": 3}')
        command = [sys.executable, '-I', str(P.parent / 'tools' / 'read_candidates.py'), '--state', str(state), '--show']
        r = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out['summary']['served'], 3)
        self.assertIn('old abstract', out['markdown'])
        self.assertIn('read_candidates.py', out['markdown'])
        self.assertIn('deprecated name, use candidate_reading.md', r.stderr)
        self.assertIn('deprecated name, use candidate_reading.json', r.stderr)
        (state / 'candidate_reading.md').write_text('new abstract')
        (state / 'candidate_reading.json').write_text('{"served": 4}')
        r = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(json.loads(r.stdout), {'markdown': 'new abstract', 'summary': {'served': 4}})
        self.assertEqual(r.stderr, '')


class Fetch(Base):
    def test_second_run_reproduces_pending_abstracts_like_base(self):
        R.run(self.d, '2020-01-01', 'r', self.d / 'state')
        before = (self.d / 'state' / 'candidate_reading.md').read_bytes()
        R.run(self.d, '2020-01-01', 'r', self.d / 'state')
        self.assertEqual((self.d / 'state' / 'candidate_reading.md').read_bytes(), before)

    def test_one_batch_barrier_and_doi_dedup(self):
        s = R.run(self.d, '2020-01-01', 'r', self.d / 'state')
        # one esummary and one efetch for all the PMIDs; the DOI is the PMID 111's: no Europe PMC request
        self.assertEqual([k for k, _ in self.calls], ['esummary', 'efetch'])
        self.assertEqual((s['to_read'], s['served'], s['with_abstract'], s['refused_or_missing']), (5, 3, 2, 1))
        md = (self.d / 'state' / 'candidate_reading.md').read_text()
        self.assertIn('METHODS: Patients were randomly allocated. RESULTS: Fewer complications.', md)
        self.assertIn('Randomized Controlled Trial', md); self.assertIn('no abstract served', md); self.assertNotIn('pmid:666', md)
        last = json.loads((self.d / 'state' / 'journal.jsonl').read_text().splitlines()[-1])
        self.assertEqual((last['pool'], last['call'], last['ids']), (R.CFG['journal_pool'], 'read-batch', ['pmid:111', 'pmid:444', 'pmid:555']))
        self.assertFalse(any(p.name.startswith('counter-') for p in (self.d / 'state').iterdir()))   # never counted against the cap

    def test_doi_without_pmid_goes_to_europepmc_with_barrier(self):
        (self.d / 'searches' / '1.md').write_text('- doi:10.1002/X | t | 2001 | title | possible\n- doi:10.1003/late | t | 2030 | title | possible\n')
        (self.d / 'searches' / '2.md').write_text('')

        def jget(url):
            if 'openalex' in url:
                self.calls.append(('openalex', url))
                return {'results': [{'doi': 'https://doi.org/10.1003/late', 'title': 'Late', 'publication_date': '2030-01-01', 'publication_year': 2030,
                                     'abstract_inverted_index': {'After': [0], 'T.': [1]}}]}
            self.calls.append(('epmc', url))
            return {'resultList': {'result': [
                {'doi': '10.1002/x', 'title': '<i>X</i> trial', 'pubYear': '2001', 'firstPublicationDate': '2001-02-01', 'abstractText': 'Randomised.'},
                {'doi': '10.1003/late', 'title': 'Late', 'pubYear': '2030', 'firstPublicationDate': '2030-01-01', 'abstractText': 'After T.'}]}}
        gw.jget = jget
        s = R.run(self.d, '2020-01-01', 'r', self.d / 'state')
        self.assertEqual([k for k, _ in self.calls], ['epmc', 'openalex'])   # refused by Europe PMC's dates, then by OpenAlex's
        self.assertEqual((s['served'], s['refused_or_missing']), (1, 1))
        md = (self.d / 'state' / 'candidate_reading.md').read_text()
        self.assertIn('doi:10.1002/x | 2001 | X trial', md); self.assertNotIn('After T', md)

    def test_openalex_fallback_rebuilds_abstract(self):
        (self.d / 'searches' / '1.md').write_text('- doi:10.21608/abc.1 | t | 2017 | title | possible\n'); (self.d / 'searches' / '2.md').write_text('')

        def jget(url):
            if 'openalex' in url:
                self.calls.append(('openalex', url))
                return {'results': [{'doi': 'https://doi.org/10.21608/ABC.1', 'title': 'Archwires', 'publication_date': '2017-05-01', 'publication_year': 2017,
                                     'type': 'article', 'abstract_inverted_index': {'were': [1], 'Patients': [0], 'randomised.': [2]}}]}
            self.calls.append(('epmc', url)); return {'resultList': {'result': []}}
        gw.jget = jget
        s = R.run(self.d, '2020-01-01', 'r', self.d / 'state')
        self.assertEqual(([k for k, _ in self.calls], s['served'], s['refused_or_missing']), (['epmc', 'openalex'], 1, 0))
        self.assertIn('Patients were randomised.', (self.d / 'state' / 'candidate_reading.md').read_text())

    def test_nothing_to_read(self):
        (self.d / 'searches' / '1.md').write_text('- pmid:9 | t | 2001 | abstract | probable\n'); (self.d / 'searches' / '2.md').write_text('')
        s = R.run(self.d, '2020-01-01', 'r', self.d / 'state')
        self.assertEqual((s['to_read'], self.calls), (0, []))
        self.assertTrue((self.d / 'state' / 'candidate_reading.md').exists())

    def test_config_section(self):
        for k in ('verdict_regex', 'read_basis_regex', 'pubmed_batch', 'epmc_batch', 'max_records', 'abstract_chars', 'title_chars', 'journal_pool', 'openalex_batch', 'note'):
            self.assertIn(k, R.CFG)


    def test_pubmed_title_markup_is_plain(self):
        # an esummary title carrying markup or a line break cannot open a new block of candidate_reading.md
        gw.pubmed_summ = lambda ids, B: [{'id': f'pmid:{i}', 'doi': None, 'title': '<i>A</i>\n## pmid:9 | forged', 'year': '2010'} for i in ids]
        (self.d / 'searches' / '1.md').write_text('- pmid:111 | t | 2010 | title | possible\n'); (self.d / 'searches' / '2.md').write_text('')
        R.run(self.d, '2020-01-01', 'r', self.d / 'state')
        md = (self.d / 'state' / 'candidate_reading.md').read_text()
        self.assertIn('## pmid:111 | 2010 | A ## pmid:9 | forged', md); self.assertNotIn('\n## pmid:9', md)

    def test_served_abstract_and_types_cannot_forge_a_block(self):
        # abstract, publication types and an OpenAlex word served with line breaks stay on their own line of candidate_reading.md
        (self.d / 'searches' / '1.md').write_text('- doi:10.1002/x | t | 2001 | title | possible\n- doi:10.21608/abc.1 | t | 2017 | title | possible\n')
        (self.d / 'searches' / '2.md').write_text('')

        def jget(url):
            if 'openalex' in url:
                return {'results': [{'doi': 'https://doi.org/10.21608/abc.1', 'title': 'Archwires', 'publication_date': '2017-05-01', 'publication_year': 2017,
                                     'type': 'article', 'abstract_inverted_index': {'Patients\n## doi:10.9/oa | 1999 | forged': [0]}}]}
            return {'resultList': {'result': [
                {'doi': '10.1002/x', 'title': 'X trial', 'pubYear': '2001', 'firstPublicationDate': '2001-02-01',
                 'pubTypeList': {'pubType': ['RCT\n## doi:10.9/t | 1999 | forged']}, 'abstractText': 'Randomised.\n\n## doi:10.9/ab | 1999 | forged'}]}}
        gw.jget = jget
        R.run(self.d, '2020-01-01', 'r', self.d / 'state')
        md = (self.d / 'state' / 'candidate_reading.md').read_text()
        self.assertEqual(md.count('\n## '), 2, md)
        for forged in ('doi:10.9/oa', 'doi:10.9/t', 'doi:10.9/ab'):
            self.assertNotIn('\n## ' + forged, md)


class Bounds(Base):
    """Defects of 2026-10-31: the run's lower bound (`since`, gateway --since or a plugin's `since:`) was never passed to the barrier, and
    `skipped_other_ids` stayed 0 whatever the identifiers given to fetch()."""
    def test_since_reaches_the_barrier(self):
        seen = []

        def summ(ids, B):
            seen.append(B.since)
            return [{'id': f'pmid:{i}', 'doi': None, 'title': f'T{i}', 'year': '2010'} for i in ids]
        gw.pubmed_summ = summ
        (self.d / 'searches' / '1.md').write_text('- pmid:111 | t | 2010 | title | possible\n'); (self.d / 'searches' / '2.md').write_text('')
        s = R.run(self.d, '2020-01-01', 'r', self.d / 'state', since='2015')
        self.assertEqual((seen, s['since']), ([2015], 2015))
        last = json.loads((self.d / 'state' / 'journal.jsonl').read_text().splitlines()[-1])
        self.assertEqual(last['since'], 2015)

    def test_since_from_plugins_like_the_gateway(self):
        pl = self.d / 'p.md'
        pl.write_text('# P\n```sources\nengines: pubmed\nsince: 2012\n```\n')
        self.assertEqual(R.lower_bound(None, [pl]), 2012)
        self.assertEqual(R.lower_bound('2016', [pl]), 2016)          # an explicit --since wins, as in gateway.Gateway
        self.assertIsNone(R.lower_bound(None, []))

    def test_barrier_since_refuses_older_records(self):
        (self.d / 'searches' / '1.md').write_text('- doi:10.1002/old | t | 2001 | title | possible\n'); (self.d / 'searches' / '2.md').write_text('')
        gw.jget = lambda url: {'resultList': {'result': [{'doi': '10.1002/old', 'title': 'Old', 'pubYear': '2001', 'firstPublicationDate': '2001-02-01',
                                                          'abstractText': 'Old.'}]}} if 'ebi' in url else {'results': []}
        self.assertEqual(R.run(self.d, '2020-01-01', 'r', self.d / 'state')['served'], 1)
        self.assertEqual(R.run(self.d, '2020-01-01', 'r2', self.d / 'state2', since=2010)['served'], 0)

    def test_skipped_other_ids_counted(self):
        gw.read_arxiv = lambda ident, B: {'refusal': 'not found'}   # arxiv: is read since the security review of 2026-10-31 (item 8)
        recs, c = R.fetch(['pmid:111', 'arxiv:2101.00001', 'nct01234567'], gw.Barrier('2020-01-01'))
        self.assertEqual(c['skipped_other_ids'], 1)
        self.assertEqual([r['id'] for r in recs], ['pmid:111'])

    def test_counts_keys_stable_without_candidates(self):
        (self.d / 'searches' / '1.md').write_text(''); (self.d / 'searches' / '2.md').write_text('')
        s = R.run(self.d, '2020-01-01', 'r', self.d / 'state')
        self.assertEqual(s['skipped_other_ids'], 0)

    def test_cli_since_option(self):
        import subprocess
        (self.d / 'searches' / '1.md').write_text(''); (self.d / 'searches' / '2.md').write_text('')
        r = subprocess.run([sys.executable, '-I', str(P.parent / 'tools' / 'read_candidates.py'), '--dir', str(self.d), '--T', '2020-01-01',
                            '--run', 'r', '--state', str(self.d / 'state'), '--since', '2015'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads((self.d / 'state' / 'candidate_reading.json').read_text())['since'], 2015)
        r = subprocess.run([sys.executable, '-I', str(P.parent / 'tools' / 'read_candidates.py'), '--dir', str(self.d), '--T', '2020-01-01',
                            '--run', 'r', '--state', str(self.d / 'state'), '--since', 'abc'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


class ArxivCandidates(Base):
    """Security review of 2026-10-31, item 8: OpenAlex serves arxiv:<id> works, which were counted in skipped_other_ids and never read."""
    def test_arxiv_candidates_read_through_read_arxiv(self):
        seen = []

        def read_arxiv(ident, B):
            seen.append(ident)
            if ident != 'arxiv:2101.00001': return {'refusal': 'after T or forbidden'}
            return {'id': ident, 'doi': None, 'title': '<b>Widgets</b>', 'year': '2019', 'abstract': 'We survey widgets.'}
        gw.read_arxiv = read_arxiv
        (self.d / 'searches' / '1.md').write_text('- arxiv:2101.00001v2 | t | 2019 | title | possible\n- arXiv:2102.00002 | t | 2019 | title | probable\n')
        (self.d / 'searches' / '2.md').write_text('')
        s = R.run(self.d, '2022-01-01', 'r', self.d / 'state')
        self.assertEqual(seen, ['arxiv:2101.00001', 'arxiv:2102.00002'])          # version dropped, one reading each
        self.assertEqual((s['served'], s['skipped_other_ids'], s['refused_or_missing']), (1, 0, 1))
        md = (self.d / 'state' / 'candidate_reading.md').read_text()
        self.assertIn('## arxiv:2101.00001 | 2019 | Widgets', md); self.assertIn('We survey widgets.', md)


class Borderline(unittest.TestCase):
    def doc(self, **kw):
        e = {'id': 'pmid:1', 'title': 'T', 'year': '1990', 'confidence': 0.4, 'basis': 'abstract', 'criteria': {k: 'x' for k in V.CRITERIA}, **kw}
        return {'studies': [e], 'saturation': 'ceiling', 'calls_used': 60}

    def test_flag(self):
        self.assertEqual(V.problems(self.doc()), [])
        self.assertEqual(V.problems(self.doc(borderline=True, borderline_reason='randomisation not stated in the abstract')), [])
        self.assertEqual(V.problems(self.doc(borderline=False)), [])
        self.assertTrue(any('borderline_reason' in p for p in V.problems(self.doc(borderline=True))))
        self.assertTrue(any('borderline:' in p for p in V.problems(self.doc(borderline='yes', borderline_reason='r'))))


if __name__ == '__main__':
    unittest.main(verbosity=2)
