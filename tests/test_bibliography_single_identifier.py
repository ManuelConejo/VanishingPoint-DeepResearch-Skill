#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""One document = one identifier: an entry carrying two configured identifiers receives no address."""
import pathlib, sys, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'tools'))
import bibliography_links as BL


class SingleIdentifier(unittest.TestCase):
    def test_two_identifiers_on_one_entry_get_no_address_and_warn(self):
        md = '## Bibliography\n[1] Smith. Response to pmid:12345. 2024. pmid:67890 (abstract)\n'
        self.assertEqual(BL.enrich(md), md)
        self.assertTrue(any('address not deducible' in w for w in BL.warnings(md)))

    def test_one_identifier_still_gets_its_address_once(self):
        md = '## Bibliography\n[1] Smith. A title. 2024. pmid:67890 (abstract)\n'
        out = BL.enrich(md)
        self.assertIn('pmid:67890 <https://pubmed.ncbi.nlm.nih.gov/67890/> (abstract)', out)
        self.assertEqual(BL.enrich(out), out)


if __name__ == '__main__':
    unittest.main()
