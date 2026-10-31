#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of validate_result.py: a well-formed result.json passes; shape deviations are named."""
import pathlib, sys, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import validate_result as V   # noqa: E702


def good():
    return {'studies': [{'id': 'pmid:35589669', 'title': 'T', 'year': '2022', 'confidence': 0.9, 'basis': 'abstract',
                         'criteria': {k: 'x' for k in V.CRITERIA}},
                        {'id': 'arxiv:1706.03762', 'title': 'U', 'year': '2017', 'confidence': 0.5, 'basis': 'title',
                         'criteria': {k: '' for k in V.CRITERIA}}],
            'saturation': 'two waves without any new eligible study', 'calls_used': 42, 'verification': {'entries_removed': 1, 'rule': 'DISTORTED removed'}}


class Test(unittest.TestCase):
    def test_good(self):
        self.assertEqual(V.problems(good()), [])
        self.assertEqual(V.CRITERIA, ['population', 'intervention_exposure', 'comparator', 'results', 'study_design', 'date_language_type'])

    def test_deviations(self):
        r = good(); r['studies'][0]['id'] = '35589669'; r['studies'][1]['confidence'] = 0.95; r['studies'][0]['basis'] = 'web'
        del r['studies'][0]['criteria']['comparator']; r['verification'] = {'entries_removed': 'one'}; r['saturation'] = ''
        pb = V.problems(r)
        for expected in ('studies[0].id', 'confidence not non-increasing', 'studies[0].basis', 'criteria.comparator', 'verification', 'saturation'):
            self.assertTrue(any(expected in p for p in pb), (expected, pb))
        r = good(); r['studies'] = r['studies'] * 26
        self.assertTrue(any('> 50' in p for p in V.problems(r)) and any('duplicate' in p for p in V.problems(r)))
        self.assertIn('missing field: calls_used', V.problems({'studies': [], 'saturation': 'x'}))
        self.assertEqual(V.problems([]), ['root: JSON object expected'])

    def test_every_gateway_id_kind(self):
        """A law run keeps its CELEX, ECLI, administrative and thesis sources (seen dropped in the run of 2026-10-28), and so on for each
        id kind the gateway serves (validate_card.IDS) and code ids <path>@<SHA>."""
        import validate_card as C
        ids = ['celex:62012CJ0131', 'ecli:ECLI:EU:C:2014:317', 'ja:CE/DCE_515092_20261027', 'hal:hal-05523091', 'thesesfr:2024PA100128',
               'nct:NCT01234567', 'dblp:conf/acl/Xiong0LZ24', 'econbiz:10011386660', 'osv:GHSA-p6mc-m468-83gw', 'openreview:hSyW5go0v8',
               'zenodo:1234567', 'biorxiv:10.1101/2020.01.01.123456', 'medrxiv:10.1101/2021.03.04.21252916', 'pmcid:PMC1234567',
               'arxiv:hep-th/9901001', 'src/model.py@0123abc', 'local:lib/x.py@0123456789abcdef0123', 'hfmodel:google-bert/bert-base-uncased',
               'repo:alharkan7/beeblio/agent/lib/openalex.ts@22a8a77dcf8ecb39d2c4adf8142c19e8974de756',
               'hfdataset:rajpurkar/squad', 'rfc:8446', 'pep:484', 'w3c:webauthn-2', 'acl:2024.acl-long.1', 'pmlr:v202/aamand23a',
               'cvf:content/CVPR2024/html/Zeng_Unmixing_Diffusion_CVPR_2024_paper',
               'judilibre:5fca56cd0a790c1ec36ddc07', 'legi:LEGIARTI000006438819', 'jorf:JORFTEXT000032004939',
               'dbnomics:ECB/ICP/M.U2.N.000000.4.ANR', 'fred:UNRATE', 'edgar:320193/0000320193-19-000119', 'ghsa:GHSA-462w-v97r-4m45', 'hudoc:001-229320', 'europarl:TA-8-2018-0529',
               'isidore:10670/1.3904e8dea2beef818dcfe30152cf9d7bde121ebc', 'isidore:20.500.13089/16ds9']
        kinds = {i.split(':', 1)[0] for i in ids if ':' in i} | {'code'}
        self.assertEqual(sorted(set(C.IDS) - kinds - {'pmid', 'doi', 'arxiv'}), [], 'a kind of validate_card.IDS without a test id')
        r = good(); r['studies'] = [dict(r['studies'][0], id=i, confidence=0.5) for i in ids]
        self.assertEqual(V.problems(r), [])
        for bad in ('S1', 'celex:', 'foo:bar', 'nct:123', 'src/model.py@nothex', 'celex:62012CJ0131 extra', 'repo:o/n/a.py@main', 'repo:onlyowner@' + 'a' * 40):
            r['studies'][0]['id'] = bad
            self.assertTrue(any('studies[0].id' in p for p in V.problems(r)), bad)

    def test_code_id_warnings(self):
        """repo:<owner>/<name>/<path>@<40-hex SHA> is the complete form (no warning); an abbreviated SHA or a path without a repository stays
        valid (no problem) but is warned, until the instructions change by duel (audit of 2026-10-31, section 6 item 1)."""
        full = 'repo:alharkan7/beeblio/agent/lib/openalex.ts@22a8a77dcf8ecb39d2c4adf8142c19e8974de756'
        self.assertEqual(V.code_warnings(full), [])
        self.assertEqual(V.code_warnings('pmid:35589669'), []); self.assertEqual(V.code_warnings('osv:GHSA-p6mc-m468-83gw'), [])
        self.assertEqual(V.code_warnings('local:lib/x.py@' + 'a' * 40), [])
        w = V.code_warnings('src/model.py@0123abc')
        self.assertEqual(len(w), 2, w); self.assertIn('abbreviated SHA (7 hex characters', w[0]); self.assertIn('no repository named', w[1])
        self.assertEqual(len(V.code_warnings('src/model.py@' + 'b' * 40)), 1)
        self.assertIn('abbreviated SHA (8', V.code_warnings('repo:alharkan7/beeblio/LICENSE.md@22a8a77d')[0])
        self.assertIn('abbreviated SHA (20', V.code_warnings('local:lib/x.py@0123456789abcdef0123')[0])
        r = good(); r['studies'] = [dict(r['studies'][0], id=i, confidence=0.5) for i in (full, 'src/model.py@0123abc')]
        self.assertEqual(V.problems(r), [])
        ws = V.warnings(r)
        self.assertEqual(len(ws), 2, ws); self.assertTrue(all(x.startswith('studies[1].id: ') for x in ws), ws)
        self.assertEqual(V.warnings(good()), []); self.assertEqual(V.warnings([]), [])


if __name__ == '__main__':
    unittest.main()
