# SPDX-License-Identifier: Apache-2.0
"""A1 round 4 oracle: explicit configuration, physical lines and fence scope."""
import ast, importlib.util, pathlib, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import bibliography_links as BL
import export_data as E
import export_report as H
import living_diff as LD


class Round4(unittest.TestCase):
    def exported(self, md):
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / 'REPORT.md').write_text(md, encoding='utf-8')
            return E.entries(tmp)

    def test_no_pattern_introspection_and_py39_guard(self):
        src = (P.parent / 'tools/bibliography_links.py').read_text()
        for forbidden in ('_parser', 'sre_parse', '_pattern_can_end_with'):
            self.assertNotIn(forbidden, src)
        ast.parse(src, feature_version=(3, 9))
        spec = importlib.util.spec_from_file_location('compat_guard', P / 'test_py39_compat.py')
        guard = importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
        for src in ('from re import _parser', 'import re\nre._parser.parse("x", 0)', 'import re._parser'):
            self.assertTrue(guard.runtime_issues(ast.parse(src)), src)

    def test_detachable_punctuation_is_opt_in(self):
        rule = {'pattern': r'(?P<id>\d+)', 'url': 'https://example.invalid/{id}'}
        for tail in '.,;':
            self.assertIsNone(BL.canonical_url('custom:123' + tail, {'custom': rule}))
            self.assertEqual(BL.canonical_url('custom:123' + tail,
                             {'custom': dict(rule, detachable_punctuation='.,;')}), 'https://example.invalid/123')
        for kind in ('acl', 'w3c', 'pmlr', 'osv'):
            ident = {'acl': '2024.acl-long.1', 'w3c': 'css-grid-1', 'pmlr': 'v202/smith23a', 'osv': 'PYSEC-2024-12'}[kind]
            self.assertEqual(BL.canonical_url(kind + ':' + ident + '.'), BL.canonical_url(kind + ':' + ident))
        for kind, ident in (('hfmodel', 'org/model'), ('hfdataset', 'org/data'),
                            ('dblp', 'conf/nips/Smith17'), ('celex', '32016R0679')):
            self.assertIsNone(BL.canonical_url(kind + ':' + ident + '.'))

    def test_no_url_for_doi_with_comma_or_semicolon(self):
        for value in ('abc,10.5678/def', 'abc;10.5678/def', 'a,b', 'a;b', 'a(b,c)', 'a(b;c)', 'a,doi:10.5555/b', 'a;doi:10.5555/b'):
            ident = 'doi:10.1234/' + value
            md = '## Bibliography\n[1] ' + ident + ' (abstract)\n'
            with self.subTest(ident=ident):
                self.assertIsNone(BL.canonical_url(ident))
                self.assertEqual(BL.enrich(md), md)
                self.assertEqual(self.exported(md)[0]['url'], '')
                self.assertNotIn('href="https://doi.org/', H.render(md, []))
                self.assertTrue(any('address not deducible' in w for w in BL.warnings(md)))

    def test_arxiv_uses_month_and_serial_length(self):
        good = ('0704.0001', '0712.9999', '0801.0001', '1412.9999', '1501.00001', '2301.12345v2', 'hep-th/9901001')
        bad = ('0703.0001', '0001.0001', '0700.0001', '0713.0001', '1412.12345', '1501.1234',
               '2301.1234', '2300.12345', '2313.12345', '2301.123456', '２３０１.12345')
        for value in good:
            self.assertEqual(BL.canonical_url('arxiv:' + value), 'https://arxiv.org/abs/' + value)
        for value in bad:
            with self.subTest(value=value): self.assertIsNone(BL.canonical_url('arxiv:' + value))

    def test_no_addresses_for_fragments_across_lines(self):
        for first, second in (('doi:10.1234/abc', 'def'), ('pmid:12345', '678'),
                              ('arxiv:2301.1234', '5'), ('arxiv:2301.12345', '6'),
                              ('openreview:abcdef', 'ghij'), ('hal:hal-01234567', 'v2'),
                              ('nct:NCT01234567', '8')):
            for ending in ('\n', '\r\n'):
                with self.subTest(first=first, ending=repr(ending)):
                    md = '## Bibliography' + ending + '[1] ' + first + ending + '    ' + second + ending
                    self.assertEqual(BL.enrich(md), md)
                    self.assertEqual(self.exported(md)[0]['url'], '')
                    self.assertTrue(any('address not deducible' in w for w in BL.warnings(md)))

        # Every physical continuation disqualifies the whole entry.
        for tail in (' (abstract)', '.', ' '):
            md = '## Bibliography\n[1] Author.\n    pmid:12345' + tail + '\n'
            self.assertEqual(BL.enrich(md), md)
            self.assertEqual(self.exported(md)[0]['url'], '')
            self.assertEqual(BL.warnings(md), [])

    def test_fences_preserve_all_bytes_inside_and_outside_bibliography(self):
        for char in ('`', '~'):
            for opening, closing in ((3, 3), (4, 4), (5, 7)):
                for indent in ('', '   ', '    ', '\t'):
                    for ending in ('\n', '\r\n'):
                        with self.subTest(char=char, opening=opening, closing=closing, indent=indent):
                            block = ending.join((indent + char * opening + 'markdown', char * (opening - 1),
                                                 '## Bibliography', '[1] pmid:12345', char * 3 + 'not a close',
                                                 '## Other', indent + char * closing, ''))
                            prefix = '# Title' + ending + 'doi:10.1234/outside' + ending
                            suffix = '## Other' + ending + '[8] pmid:99999' + ending
                            valid = '## Bibliography' + ending + '[2] pmid:67890' + ending
                            md = prefix + block + valid + suffix
                            enriched = BL.enrich(md)
                            self.assertTrue(enriched.startswith(prefix + block))
                            self.assertTrue(enriched.endswith(suffix))
                            self.assertEqual(enriched.count('<https://'), 1)
                            self.assertIn('<https://pubmed.ncbi.nlm.nih.gov/67890/>', enriched)
                            self.assertEqual(BL.enrich(enriched), enriched)
                            inside = '## Bibliography' + ending + '[2] pmid:67890' + ending + block
                            self.assertTrue(BL.enrich(inside).endswith(block))
        for closer in ('~~~', '```suffix', '``', '````suffix'):
            md = '````markdown\n' + closer + '\n## Bibliography\n[1] pmid:12345\n'
            self.assertEqual(BL.enrich(md), md)

    def test_fenced_code_opened_in_a_list_is_untouched(self):
        for marker in ('- ', '* ', '+ ', '1. ', '2) ', '- 1. '):
            block = marker + '````markdown\n  ## Bibliography\n  [1] pmid:12345\n  - ````\n  [2] pmid:54321\n  ````\n'
            md = block + '## Bibliography\n[3] pmid:67890\n'
            with self.subTest(marker=marker):
                enriched = BL.enrich(md)
                self.assertTrue(enriched.startswith(block))
                self.assertEqual(enriched.count('<https://'), 1)
                self.assertIn('<https://pubmed.ncbi.nlm.nih.gov/67890/>', enriched)

    def test_living_year_ignores_enriched_arxiv_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            (folder / 'card.json').write_text('{}')
            md = '## Bibliography\n[1] Author. A title. 2020. arxiv:2005.14165 (abstract)\n'
            (folder / 'REPORT.md').write_text(md)
            before = LD.read_run(folder)['sources']['S1']
            (folder / 'REPORT.md').write_text(BL.enrich(md))
            after = LD.read_run(folder)['sources']['S1']
            self.assertEqual(after['year'], '2020')
            self.assertEqual(after['tkey'], before['tkey'])

    def test_invented_report_keeps_all_canonical_addresses(self):
        md = ('# Invented report\n## Bibliography\n'
              '[1] Example A. Synthetic paper. 2024. pmid:12345. Basis: abstract.\n'
              '[2] Example B. Synthetic preprint. 2023. arxiv:2301.12345 (title)\n'
              '[3] Example C. Synthetic study. doi:10.1234/invented (abstract)\n'
              '## Methodology Appendix\nOffline example.\n')
        enriched = BL.enrich(md)
        entries = list(BL.entry_lines(enriched))
        self.assertEqual(len(entries), 3)
        self.assertEqual(sum(bool(BL.URL.search(body)) for _, _, body in entries), 3)
        self.assertEqual(BL.warnings(enriched), [])
        self.assertEqual(BL.enrich(enriched), enriched)

    def assert_rejected(self, md, warns=True):
        self.assertEqual(BL.enrich(md), md)
        self.assertEqual(any('address not deducible' in w for w in BL.warnings(md)), warns)
        self.assertFalse(any(e['url'] for e in self.exported(md)))
        page = H.render(md, [])
        for host in ('doi.org', 'pubmed.ncbi.nlm.nih.gov', 'arxiv.org', 'aclanthology.org', 'www.w3.org'):
            self.assertNotIn('href="https://' + host + '/', page)

    def test_review_a_trailing_spaces_before_continuation(self):
        for tail in ('', ' ', '  ', '\t', '.', '. ', ' (abstract)'):
            for ending in ('\n', '\r\n'):
                for indent in (' ', '  ', '    ', '\t'):
                    self.assert_rejected('## Bibliography' + ending + '[1] doi:10.1234/alpha' + tail + ending
                                         + indent + 'beta (abstract)' + ending)

    def test_review_a_code_comments_and_strict_entry_start(self):
        for md in ('## Bibliography\n\n    [1] pmid:12345\n',
                   '<!--\n## Bibliography\n[1] pmid:12345\n-->\n',
                   '```md\n## Bibliography\n[1] pmid:12345\n```\n',
                   '``` <!-- info -->\n## Bibliography\n[1] pmid:12345\n```\n',
                   '    ## Bibliography\n[1] pmid:12345\n',
                   '\t## Bibliography\n[1] pmid:12345\n',
                   '## Bibliography\n [1] pmid:12345\n',
                   '## Bibliography\n[1]pmid:12345\n',
                   '## Bibliography\n[1]\tpmid:12345\n',
                   '## Bibliography\n<!-- [1] pmid:12345 -->\n',
                   '## Bibliography\n[1] pmid:12345 <!-- hidden -->\n',
                   '## Bibliography\n[1] `pmid:12345`\n'):
            with self.subTest(md=md): self.assert_rejected(md, warns=False)

    def test_comment_and_code_do_not_change_section(self):
        for block in ('<!--\n## Other\n-->\n', '```\n## Other\n```\n', '    ## Other\n\n'):
            md = '## Bibliography\n' + block + '[1] pmid:12345\n'
            self.assertIn('<https://pubmed.ncbi.nlm.nih.gov/12345/>', BL.enrich(md))
        self.assert_rejected('## Other\n<!-- ## Bibliography -->\n[1] pmid:12345\n', warns=False)

    def test_review_b_unindented_continuation(self):
        for first, rest in (('doi:10.1234/abc', 'def (abstract)'), ('arxiv:2301.12345v1', '2 (abstract)')):
            self.assert_rejected('## Bibliography\n[1] Author. ' + first + '\n' + rest + '\n')

    def test_review_b_title_abbreviations_and_unicode(self):
        for text in ('Proceedings of ACL:Findings, 2021', 'W3C:Recommendation',
                     'pmid:１２３４５', 'doi:10.１２３４/a', 'zenodo:１２３４５', 'openreview:abcdefé',
                     'biorxiv:10.1101/123456', 'medrxiv:10.1101/123456', 'dbnomics:AMECO/x',
                     'fred:SERIES', 'local:x.py@abcdef1', 'code:x.py@abcdef1'):
            self.assert_rejected('## Bibliography\n[1] ' + text + '\n',
                                 warns=text.split(':', 1)[0] not in ('biorxiv', 'medrxiv', 'dbnomics', 'fred', 'local', 'code'))

    def test_exports_do_not_infer_in_prose_or_from_card(self):
        md = '## Other\npmid:12345\n'
        self.assertNotIn('href="https://pubmed.ncbi.nlm.nih.gov/', H.render(md, []))
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / 'REPORT.md').write_text('## Bibliography\n[1] Invented title.\n')
            (d / 'card.json').write_text('{"sources":{"S1":{"pmid":"12345"}}}')
            self.assertEqual(E.entries(tmp)[0]['url'], '')

    def test_existing_noncanonical_url_is_retained(self):
        for ident, written, canonical in (
                ('doi:10.1234/A', 'https://doi.org/10.1234/a', 'https://doi.org/10.1234/A'),
                ('doi:10.1234/a+b', 'https://doi.org/10.1234/a+b', 'https://doi.org/10.1234/a%2Bb')):
            md = '## Bibliography\n[1] ' + ident + ' <' + written + '>\n'
            enriched = BL.enrich(md)
            self.assertIn('<' + written + '>', enriched)
            self.assertIn('<' + canonical + '>', enriched)
            self.assertEqual(BL.enrich(enriched), enriched)



if __name__ == '__main__': unittest.main()
