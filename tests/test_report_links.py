# SPDX-License-Identifier: Apache-2.0
"""Offline regression oracles for canonical bibliography URLs."""
import importlib, json, pathlib, re, shutil, sys, tempfile, unittest
from unittest.mock import patch
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import validate_card as V
import finish_run as F
import export_data as E
import export_report as H
import study_family as SF
import prisma
import verifier
import check_code_refs as CR

CASES = {
    'doi:10.1234/a(b)': 'https://doi.org/10.1234/a(b)',
    'pmid:12345': 'https://pubmed.ncbi.nlm.nih.gov/12345/',
    'arxiv:2301.12345v2': 'https://arxiv.org/abs/2301.12345v2',
    'arxiv:hep-th/9901001': 'https://arxiv.org/abs/hep-th/9901001',
    'openreview:Abc_123-': 'https://openreview.net/forum?id=Abc_123-',
    'celex:32016R0679': 'https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679',
    'hal:hal-01234567v2': 'https://hal.science/hal-01234567v2',
    'thesesfr:2019PA066123': 'https://theses.fr/2019PA066123',
    'nct:NCT01234567': 'https://clinicaltrials.gov/study/NCT01234567',
    'dblp:conf/nips/Smith17': 'https://dblp.org/rec/conf/nips/Smith17',
    'econbiz:100123': 'https://www.econbiz.de/Record/100123',
    'osv:PYSEC-2024-12': 'https://osv.dev/vulnerability/PYSEC-2024-12',
    'zenodo:1234567': 'https://zenodo.org/records/1234567',
    'hfmodel:org/model': 'https://huggingface.co/org/model',
    'hfdataset:org/data': 'https://huggingface.co/datasets/org/data',
    'rfc:9110': 'https://www.rfc-editor.org/rfc/rfc9110',
    'pep:8': 'https://peps.python.org/pep-0008/',
    'w3c:css-grid-1': 'https://www.w3.org/TR/css-grid-1/',
    'acl:2024.acl-long.1': 'https://aclanthology.org/2024.acl-long.1/',
    'pmlr:v202/smith23a': 'https://proceedings.mlr.press/v202/smith23a.html',
    'cvf:content/CVPR2024/html/Smith_Title_CVPR_2024_paper': 'https://openaccess.thecvf.com/content/CVPR2024/html/Smith_Title_CVPR_2024_paper.html',
    'edgar:0000320193/0000320193-19-000119': 'https://www.sec.gov/Archives/edgar/data/320193/000032019319000119/0000320193-19-000119-index.htm',
    'ghsa:GHSA-2345-cfgh-jmpq': 'https://github.com/advisories/GHSA-2345-cfgh-jmpq',
}

class Links(unittest.TestCase):
    def setUp(self):
        self.L = importlib.import_module('bibliography_links')

    def test_rules_and_no_guesses(self):
        for ident, expected in CASES.items():
            with self.subTest(ident=ident): self.assertEqual(self.L.canonical_url(ident), expected)
        for ident in ('ecli:ECLI:FR:CCASS:2020:C100001', 'ja:CE/x.xml', 'local:x.py@abc1234',
                      'pmid:bad', 'unknown:123', 'openreview:bad?evil=1'):
            with self.subTest(ident=ident): self.assertIsNone(self.L.canonical_url(ident))

    def test_config_drives_rules(self):
        cfg = {'custom': {'pattern': r'(?P<id>[A-Z]+)', 'url': 'https://example.invalid/{id}'}}
        self.assertEqual(self.L.canonical_url('custom:ABC', rules=cfg), 'https://example.invalid/ABC')
        self.assertIsNone(self.L.canonical_url('doi:10.1234/x', rules=cfg))

    def test_scoped_idempotent_preserves_bytes(self):
        for heading in ('Bibliography', 'Bibliographie'):
            before = '# R\r\n## Introduction\r\nRaw doi:10.1234/x [1].\r\n## ' + heading + '\r\n'
            entry = '[1] A. Title. 2024. doi:10.1234/a(b) (abstract)\r\n'
            after = '## Methodology Appendix\r\ndoi:10.1234/y\r\n'
            original = before + entry + after
            result = self.L.enrich(original)
            self.assertTrue(result.startswith(before)); self.assertTrue(result.endswith(after))
            self.assertIn('doi:10.1234/a(b) <https://doi.org/10.1234/a(b)> (abstract)', result)
            self.assertEqual(result, self.L.enrich(result))
            self.assertEqual(self.L.missing(result), [])
            self.assertEqual(len(self.L.missing(original)), 1)
        bare = '# R\n## Introduction\ndoi:10.1234/x\n'
        self.assertEqual(self.L.enrich(bare), bare)

    def test_existing_urls_multiple_ids_and_safety(self):
        md = '## Bibliography\n[1] A. doi:10.1234/x pmid:12345 (title)\n[2] B. openreview:Abc_123- <https://other.invalid/>\n'
        result = self.L.enrich(md)
        # one document = one identifier: entry [1] carries two and is left unchanged, with a warning
        self.assertIn('[1] A. doi:10.1234/x pmid:12345 (title)\n', result)
        for url in ('https://doi.org/10.1234/x', CASES['pmid:12345']): self.assertNotIn('<' + url + '>', result)
        self.assertTrue(any('[1]' in w and 'address not deducible' in w for w in self.L.warnings(md)))
        self.assertIn('<' + CASES['openreview:Abc_123-'] + '>', result)
        self.assertEqual(result, self.L.enrich(result))
        self.assertEqual(self.L.missing(result), [])
        self.assertIsNone(self.L.canonical_url('doi:10.1234/a#b?c&d'))
        linked = '## Bibliography\n[1] A. doi:10.1234/x [record](https://doi.org/10.1234/x)\n'
        self.assertEqual(self.L.enrich(linked), linked)

    def test_validation_reports_missing_without_mutating(self):
        md = '## Bibliography\n[1] A. openreview:Abc_123- (abstract)\n'
        self.assertFalse(any('canonical URL' in p for p in V.report_problems(md)))
        self.assertTrue(any('canonical URL' in p for p in self.L.warnings(md)))
        self.assertFalse(any('canonical URL' in p for p in V.report_problems(self.L.enrich(md))))

    def test_finish_before_receipt_and_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp) / 'run'; shutil.copytree(P / 'fixtures' / 'finish_run', d)
            original = re.sub(r' <https?://[^>]+>', '', (d / 'REPORT.md').read_text())
            (d / 'REPORT.md').write_text(original)
            observed = []
            def run(args):
                observed.append(((d / 'REPORT.md').read_text(), V.end_problems(d)))
                return 0, 'OK'
            with patch.object(F, '_run', side_effect=run), patch.object(F, 'contradictor_offer', return_value=None):
                result = F.finish(d, offline=True)
                first = (d / 'REPORT.md').read_bytes()
                F.finish(d, offline=True)
            self.assertTrue(result['validation_passed'])
            self.assertNotEqual(first.decode(), original)
            self.assertEqual(first, (d / 'REPORT.md').read_bytes())
            self.assertTrue(all(self.L.missing(text) == [] and pb == [] for text, pb in observed))
            self.assertEqual(V.end_problems(d), [])

    def test_every_new_format_in_data_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            md = '## Bibliography\n' + ''.join(f'[{n}] Smith. Title. 2024. {ident} basis: abstract\n' for n, ident in enumerate(CASES, 1))
            (d / 'REPORT.md').write_text(self.L.enrich(md))
            es = E.entries(d)
            for e, (ident, url) in zip(es, CASES.items()):
                with self.subTest(ident=ident):
                    self.assertEqual(e['ids'], [ident])
                    self.assertEqual(e['url'], url)
                    self.assertEqual(e['basis'], 'abstract')

    def test_readers_preserve_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp) / 'run'; shutil.copytree(P / 'fixtures' / 'finish_run', d)
            before = re.sub(r' <https?://[^>]+>', '', (d / 'REPORT.md').read_text())
            (d / 'REPORT.md').write_text(before)
            before_e = E.entries(d); before_sf = SF.of_dir(d); before_p = prisma.build(d)
            (d / 'REPORT.md').write_text(self.L.enrich(before))
            after_e = E.entries(d)
            for a, b in zip(before_e, after_e):
                for key in ('n', 'ids', 'vp_id', 'doi', 'title', 'year', 'basis', 'authors'): self.assertEqual(a[key], b[key], key)
                self.assertTrue(b['url'].startswith('https://'))
            self.assertEqual(before_sf, SF.of_dir(d))
            self.assertEqual(before_p, prisma.build(d))
            html = H.render((d / 'REPORT.md').read_text(), [])
            self.assertIn('href="https://pubmed.ncbi.nlm.nih.gov/', html)
            for export in (E.bibtex, E.ris, E.csl): self.assertIn('https://pubmed.ncbi.nlm.nih.gov/', export(after_e))
            card = json.loads((d / 'card.json').read_text())
            self.assertEqual(verifier.key_of(card['claims'][0], card), 'S1')
            self.assertEqual(verifier.ident_of(card['sources']['S1']), 'doi:10.1000/fx.retracted')
            self.assertEqual(CR.extract(d / 'REPORT.md')['refs'], [])

if __name__ == '__main__': unittest.main()
