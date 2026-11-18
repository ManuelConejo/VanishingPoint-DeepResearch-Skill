# SPDX-License-Identifier: Apache-2.0
"""Round 2 regression oracles; deliberately fail before the implementation fix."""
import importlib, json, pathlib, shutil, sys, tempfile, unittest
from unittest.mock import patch
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P)); sys.path.insert(0, str(P.parent / 'tools'))
import bibliography_links as BL
import export_report as H
import export_data as E
import validate_card as V
import finish_run as F
from test_validate_card import REPORT_MD, folder

class Round2(unittest.TestCase):
    def test_ambiguous_identifiers_never_produce_an_address(self):
        tails = ('<b>', '>tail', '<693::AID-ASI4>3.0.CO;2-O', '?', '!', ':', '"', "'", '**', '_', '[1]', '[note]', '..', ',', ';', ')', '`', '\\x', '&amp;tail')
        for tail in tails:
            with self.subTest(tail=tail):
                raw = 'doi:10.1234/example' + tail
                md = '## Bibliography\n[1] Author. ' + raw + ' (abstract)\n'
                self.assertEqual(BL.enrich(md), md)
                self.assertNotIn('href="https://doi.org/', H.render(md, []))
                with tempfile.TemporaryDirectory() as tmp:
                    (pathlib.Path(tmp)/'REPORT.md').write_text(md)
                    self.assertTrue(any('address not deducible' in w for w in V.warnings(tmp)))
        for raw in ('doi:10.1002/(SICI)1097-4571(199806)49:8<693::AID-ASI4>3.0.CO;2-O',
                    '**doi:10.1234/a**', '"doi:10.1234/a"', '[doi:10.1234/a](target)', '<doi:10.1234/a>',
                    '`doi:10.1234/a`?', '`doi:10.1234/a`<tag>'):
            md = '## Bibliography\n[1] ' + raw + '\n'
            self.assertEqual(BL.enrich(md), md, raw)
            self.assertNotIn('href="https://doi.org/', H.render(md, []), raw)

    def test_html_and_printed_url_share_parentheses_and_rules(self):
        for ident in ('doi:10.1234/a(b)', 'pep:8', 'openreview:Abc_123-'):
            md = BL.enrich('## Bibliography\n[1] Author. ' + ident + ' (abstract)\n')
            url = BL.canonical_url(ident)
            page = H.render(md, [])
            self.assertEqual(page.count('href="' + url + '"'), 2, page)
            self.assertNotIn('href="https://doi.org/10.1234/a(b"', page)

    def test_existing_bare_canonical_url_keeps_balanced_parenthesis(self):
        url='https://doi.org/10.1234/a(b)'
        md='## Bibliography\n[1] Author. doi:10.1234/a(b) '+url+' (abstract)\n'
        self.assertEqual(BL.enrich(md),md)
        page=H.render(md,[])
        self.assertEqual(page.count('href="'+url+'"'),2)
        self.assertNotIn('href="https://doi.org/10.1234/a(b"',page)

    def test_bibliography_stops_at_h1_and_h2(self):
        for heading in ('# New chapter', '## Other chapter', ' # Indented chapter', '   ## Indented section'):
            suffix = heading + '\n[2] doi:10.1234/other\n'
            md = '## Bibliography\n[1] doi:10.1234/a\n' + suffix
            self.assertTrue(BL.enrich(md).endswith(suffix))
            self.assertEqual([n for _,n,_ in BL.entry_lines(md)], [1])
            self.assertEqual([n for n,_ in E.bib_entries(md)], [1])

    def test_continuation_identifier_is_untouched(self):
        md = '# Title\r\n## Bibliography\r\n[1] Author. Title.\r\n    doi:10.1234/a(b) (abstract)\r\n## Methodology Appendix\r\nUntouched\r\n'
        enriched = BL.enrich(md)
        self.assertEqual(enriched, md)
        self.assertNotIn('href="https://doi.org/', H.render(md, []))
        self.assertEqual(enriched, BL.enrich(enriched))
        self.assertEqual(BL.missing(md), [])
        self.assertEqual(BL.warnings(md), [])  # The entry line itself carries no identifier.
        self.assertEqual(len(E.bib_entries(enriched)), 1)
        self.assertNotIn('\n', enriched.replace('\r\n',''))

    def test_invalid_utf8_finish_and_atomic_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)/'run'; shutil.copytree(P/'fixtures'/'finish_run', d)
            p = d/'REPORT.md'
            raw = p.read_bytes() + b'\nInvalid: \xff\n'
            raw = raw.replace(b'## Bibliography\n', b'## Bibliography\n[99] doi:10.1234/new\n')
            p.write_bytes(raw)
            with patch('os.replace', side_effect=OSError('interrupted')):
                with self.assertRaises(OSError): BL.enrich_file(p)
            self.assertEqual(p.read_bytes(), raw)
            self.assertEqual(list(d.glob('.REPORT.md.*')), [])
            with patch.object(F, '_run', return_value=(0,'OK')), patch.object(F, 'contradictor_offer', return_value=None):
                self.assertTrue(F.finish(d, offline=True)['validation_passed'])
            self.assertIn(b'Invalid: \xff', p.read_bytes())
            self.assertIn(b'<https://doi.org/10.1234/new>', p.read_bytes())
            self.assertEqual(V.end_problems(d), [])
            V.warnings(d)

    def test_doi_registrant_uses_four_to_nine_digits(self):
        for digits in ('1', '12', '123', '1234567890'):
            self.assertIsNone(BL.canonical_url('doi:10.' + digits + '/a'))
        for digits in ('1234','123456789'):
            self.assertIsNotNone(BL.canonical_url('doi:10.' + digits + '/a'))

    def test_old_report_missing_url_warns_without_failure_or_mutation(self):
        import re
        md = re.sub(r' <https?://[^>]+>', '', REPORT_MD).replace('10.1/a', '10.1234/a')
        with tempfile.TemporaryDirectory() as tmp:
            d=folder(tmp, **{'REPORT.md':md})
            self.assertEqual(V.problems(d), [])
            self.assertTrue(any('11 ' in w and 'canonical URL' in w for w in V.warnings(d)))
            self.assertEqual((d/'REPORT.md').read_text(), md)

    def test_exports_never_infer_from_trimmed_or_corrupt_identifiers(self):
        for raw in ('doi:10.1234/example..', 'doi:10.1234/example)', 'doi:10.1234/a\ufffd', 'doi:10.1234/a\x00', 'doi:10.1234/a{note}'):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as tmp:
                md='## Bibliography\n[1] Author. '+raw+' (abstract)\n'
                (pathlib.Path(tmp)/'REPORT.md').write_text(md)
                self.assertEqual(E.entries(tmp)[0]['url'], '')
                self.assertNotIn('href="https://doi.org/', H.render(md, []))



if __name__ == '__main__': unittest.main()
