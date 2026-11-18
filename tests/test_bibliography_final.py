# SPDX-License-Identifier: Apache-2.0
"""Final targeted regression oracles, offline."""
import pathlib, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import bibliography_links as BL
import export_data as E
import export_report as H


class Final(unittest.TestCase):
    def exported(self, md):
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / 'REPORT.md').write_bytes(md.encode('utf-8'))
            return E.entries(tmp)

    def test_warning_scope(self):
        quiet = ('[1] prose pmid:bad\n## Bibliography\n[2] Title only.\n'
                 '[3] unknown:value\n[4] biorxiv:10.1101/123456\n'
                 '[5] `text pmid:bad example`\n\n'
                 '    [6] pmid:bad\n<!--\n[7] pmid:bad\n-->\n'
                 '```\n[8] pmid:bad\n```\n## Other\n[9] pmid:bad\n')
        self.assertEqual(BL.warnings(quiet), [])
        for body in ('pmid:bad', 'doi:10.1234/a\n    continuation',
                     'Title. pmid:bad pmid:12345 <https://pubmed.ncbi.nlm.nih.gov/12345/>'):
            md = 'Citation [1].\n## Bibliography\n[1] ' + body + '\n'
            warnings = [w for w in BL.warnings(md) if 'address not deducible' in w]
            self.assertEqual(len(warnings), 1, warnings)
            self.assertIn('bibliography [1]', warnings[0])
        self.assertEqual(BL.warnings('## Bibliography\n[1] pmid:12345 <https://pubmed.ncbi.nlm.nih.gov/12345/>\n'), [])

    def test_only_lf_separates_physical_lines(self):
        for sep in ('\r', '\u2028', '\u2029', '\x0b', '\x0c', '\x85', '\x1c', '\x1d', '\x1e'):
            with self.subTest(separator=repr(sep)):
                md = '## Bibliography\nNote' + sep + '[1] pmid:12345\n\n[2] pmid:67890\n'
                self.assertEqual([n for _, n, _ in BL.entry_lines(md)], [2])
                enriched = BL.enrich(md)
                self.assertTrue(enriched.startswith('## Bibliography\nNote' + sep + '[1] pmid:12345\n'))
                self.assertEqual([e['n'] for e in self.exported(md)], [2])
                self.assertNotIn('href="https://pubmed.ncbi.nlm.nih.gov/12345/', H.render(md, []))
                self.assertIn('href="https://pubmed.ncbi.nlm.nih.gov/67890/', H.render(md, []))
                self.assertEqual(len(BL.missing(md)), 1)
                self.assertEqual(BL.warnings(enriched), [])
                false_heading = 'Prose' + sep + '## Bibliography\n[1] pmid:12345\n'
                self.assertEqual(BL.enrich(false_heading), false_heading)
                self.assertEqual(self.exported(false_heading), [])
        for ending in ('\n', '\r\n'):
            md = '## Bibliography' + ending + '[1] pmid:12345' + ending
            self.assertTrue(BL.enrich(md).endswith(ending))
            self.assertEqual(len(self.exported(md)), 1)

    def test_inline_code_is_not_a_reference(self):
        for code in ('`text pmid:12345 example`', '``text ` pmid:12345 example``',
                     '```text `` pmid:12345 example```', '`pmid:12345`'):
            with self.subTest(code=code):
                md = '## Bibliography\n[1] Example ' + code + '\n'
                self.assertEqual(BL.enrich(md), md)
                self.assertEqual(BL.warnings(md), [])
                entry = self.exported(md)[0]
                self.assertEqual(entry['url'], '')
                self.assertEqual(entry['ids'], [])
                self.assertNotIn('href="https://pubmed.ncbi.nlm.nih.gov/', H.render(md, []))
                mixed = md.rstrip('\n') + ' pmid:67890\n'
                enriched = BL.enrich(mixed)
                self.assertNotIn('/12345/', enriched)
                self.assertIn('/67890/', enriched)
                self.assertEqual(self.exported(mixed)[0]['ids'], ['pmid:67890'])

    def test_inline_code_does_not_create_token_boundaries(self):
        for body in ('`example`pmid:12345', 'pmid:12345`example`'):
            md = '## Bibliography\n[1] ' + body + '\n'
            with self.subTest(body=body):
                self.assertEqual(BL.enrich(md), md)
                self.assertEqual(self.exported(md)[0]['url'], '')
                self.assertNotIn('href="https://pubmed.ncbi.nlm.nih.gov/', H.render(md, []))

    def test_changelog_states_limits_and_warning_scope(self):
        text = (P.parent / 'CHANGELOG.md').read_text(encoding='utf-8')
        for required in ('one physical line', 'setext', '<pre>', '<script>', 'comment markers inside inline code',
                         'exactly one configured identifier', 'address not deducible', 'not a Markdown parser'):
            self.assertIn(required, text)
        self.assertNotIn('all other `REPORT.md` bytes are preserved', text)
        self.assertNotIn('Headings in those contexts do not open or close the section.', text)


if __name__ == '__main__':
    unittest.main()
