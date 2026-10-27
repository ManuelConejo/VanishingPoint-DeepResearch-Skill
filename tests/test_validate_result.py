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


if __name__ == '__main__':
    unittest.main()
