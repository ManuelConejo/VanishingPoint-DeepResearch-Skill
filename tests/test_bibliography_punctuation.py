# SPDX-License-Identifier: Apache-2.0
"""A1 convergence oracles: punctuation, entry boundaries and broken tokens."""
import pathlib, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import bibliography_links as BL
import export_data as E
import export_report as H

class Round3(unittest.TestCase):
    def exported(self, md):
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / 'REPORT.md').write_text(md, encoding='utf-8')
            return E.entries(tmp)

    def test_sentence_punctuation_by_configuration(self):
        cases = {
            'pmid:12345': 'https://pubmed.ncbi.nlm.nih.gov/12345/',
            'pmcid:PMC12345': 'https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12345/',
            'arxiv:2301.12345v2': 'https://arxiv.org/abs/2301.12345v2',
            'arxiv:hep-th/9901001': 'https://arxiv.org/abs/hep-th/9901001',
            'nct:NCT01234567': 'https://clinicaltrials.gov/study/NCT01234567',
            'openreview:XqIKVZmB1f': 'https://openreview.net/forum?id=XqIKVZmB1f',
        }
        for ident, url in cases.items():
            for punctuation in '.,;':
                with self.subTest(ident=ident, punctuation=punctuation):
                    md = '## Bibliography\n[1] Author. ' + ident + punctuation + ' Basis: abstract.\n'
                    self.assertEqual(BL.canonical_url(ident + punctuation), url)
                    enriched = BL.enrich(md)
                    self.assertIn(ident + punctuation + ' <' + url + '> Basis: abstract.', enriched)
                    self.assertEqual(BL.enrich(enriched), enriched)
                    self.assertEqual(BL.warnings(enriched), [])
                    self.assertEqual(self.exported(md)[0]['url'], url)
                    self.assertIn('>' + ident + '</a>' + punctuation + ' Basis', H.render(md, []))

    def test_doi_detaches_exactly_one_sentence_period(self):
        cases = (
            ('[1] Author. 2026. doi:10.64898/2026.10.11.757921. abstract',
             '10.64898/2026.10.11.757921'),
            ('[1] doi:10.1093/x. Basis: abstract.', '10.1093/x'),
            ('[1] doi:10.1234/abc.', '10.1234/abc'),
        )
        for body, value in cases:
            for ending in ('', '\n', '\r\n'):
                with self.subTest(body=body, ending=repr(ending)):
                    md = '## Bibliography\n' + body + ending
                    url = 'https://doi.org/' + value
                    self.assertEqual(BL.canonical_url('doi:' + value + '.'), url)
                    enriched = BL.enrich(md)
                    self.assertIn(body, enriched.replace(' <' + url + '>', ''))
                    self.assertIn('<' + url + '>', enriched)
                    self.assertEqual(BL.enrich(enriched), enriched)
                    self.assertEqual(BL.warnings(enriched), [])
                    self.assertEqual(self.exported(md)[0]['url'], url)
                    self.assertIn('<a href="' + url + '">doi:' + value + '</a>.', H.render(md, []))
        for tail in ('..', '...', ',', ';', '.,', '.;', ',.', ';.',
                     '.\tBasis', '-.', '/.', '+.', '<b>.', '?.'):
            with self.subTest(tail=tail):
                md = '## Bibliography\n[1] doi:10.1234/abc' + tail + '\n'
                self.assertEqual(BL.enrich(md), md)
                self.assertEqual(self.exported(md)[0]['url'], '')
                self.assertNotIn('href="https://doi.org/', H.render(md, []))
                self.assertTrue(any('address not deducible' in w for w in BL.warnings(md)))

    def test_unknown_family_punctuation_is_explicit(self):
        for pattern in (r'(?P<id>\d+)', r'(?P<id>[A-Z]+\d{2})',
                        r'(?P<id>\d+\.\d+)', r'(?P<id>(?:[A-Z]+|\d+)(?:v\d+)?)',
                        r'(?P<id>[^.,;]+)', r'(?P<id>\w+)'):
            ident = '12.34' if r'\.' in pattern else 'ABC12' if '[A-Z]+\\d' in pattern else '123'
            cfg = {'newfamily': {'pattern': pattern, 'url': 'https://example.invalid/{id}', 'detachable_punctuation': '.,;'}}
            # Select a matching value independently of the punctuation logic.
            import re
            ident = next(x for x in (ident, 'ABC12', 'ABC', '123', '12.34') if re.fullmatch(pattern, x))
            for char in '.,;':
                self.assertEqual(BL.canonical_url('newfamily:' + ident + char, cfg), 'https://example.invalid/' + ident)
        for pattern in (r'(?P<id>[\w.,;]+)', r'(?P<id>.+)', r'(?P<id>\S+)', r'(?P<id>\d+[.,;]?)'):
            cfg = {'newfamily': {'pattern': pattern, 'url': 'https://example.invalid/{id}'}}
            for char in '.,;':
                self.assertIsNone(BL.canonical_url('newfamily:123' + char, cfg))

    def test_real_report_forms(self):
        md = ('## Bibliography\n'
              '[1] Author. openreview:XqIKVZmB1f. Basis: abstract.\n'
              '[2] Author. doi:10.1038/s41558-019-0668-5 (title)\n')
        expected = ['https://openreview.net/forum?id=XqIKVZmB1f', 'https://doi.org/10.1038/s41558-019-0668-5']
        enriched = BL.enrich(md)
        self.assertEqual([e['url'] for e in self.exported(md)], expected)
        for url in expected:
            self.assertIn('<' + url + '>', enriched)
            self.assertEqual(H.render(enriched, []).count('href="' + url + '"'), 2)
        self.assertEqual(BL.enrich(enriched), enriched)
        self.assertEqual(BL.warnings(enriched), [])

    def test_notes_are_never_entry_continuations(self):
        for ending in ('\n', '\r\n'):
            for gap in ('', ending):
                prefix = '## Bibliography' + ending + '[1] Author. doi:10.1234/a' + ending
                note = gap + 'Note: doi:10.1234/note' + ending + '    pmid:99999' + ending
                second = '[2] Author. pmid:12345 ' + ending + '    (abstract)' + ending
                md = prefix + note + second
                entries = list(BL.entry_lines(md))
                self.assertEqual(entries[0][2], '[1] Author. doi:10.1234/a' + ending)
                enriched = BL.enrich(md)
                self.assertIn(note, enriched)
                self.assertNotIn('https://doi.org/10.1234/note', enriched)
                self.assertNotIn('https://pubmed.ncbi.nlm.nih.gov/99999/', enriched)
                self.assertEqual([e['url'] for e in self.exported(enriched)],
                                 ['https://doi.org/10.1234/a' if gap else '', ''])
                self.assertTrue(all('Note:' not in body for _, body in E.bib_entries(md)))
                self.assertEqual(BL.enrich(enriched), enriched)

    def test_blank_line_ends_even_indented_continuation(self):
        md = '## Bibliography\n[1] pmid:12345\n\n    Note: doi:10.1234/note\n'
        self.assertEqual(list(BL.entry_lines(md))[0][2], '[1] pmid:12345\n')
        self.assertTrue(BL.enrich(md).endswith('\n\n    Note: doi:10.1234/note\n'))

    def test_doi_continuations_even_after_a_period_have_no_address(self):
        for tail in ('-', '/', '+', '.', ',', ';'):
            md = '## Bibliography\n[1] doi:10.1234/abc' + tail + '\n    continuation (abstract)\n'
            with self.subTest(tail=tail):
                self.assertEqual(BL.enrich(md), md)
                self.assertEqual(self.exported(md)[0]['url'], '')
                self.assertNotIn('href="https://doi.org/', H.render(md, []))
                self.assertTrue(any('address not deducible' in w for w in BL.warnings(md)))



if __name__ == '__main__': unittest.main()
