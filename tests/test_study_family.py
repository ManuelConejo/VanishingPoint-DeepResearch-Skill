#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of tools/study_family.py and of its use by check 14 (tools/cross_source.py, validate_card.py): constructed cases of one
study under several forms (arXiv preprint and article, DataCite arXiv DOI, recorded Crossref relation, same trial registration, full
report and journal article of one meta-analysis) are grouped; neighbours that are separate studies (a pilot trial, another first author,
short titles, court decisions, two sites of a local evaluation, a large year gap) are not; a cross-source statement citing two versions of
one study is flagged, and so is "three trials" over three documents of two studies; config `study_family.enabled` = false restores one
study per entry. The titles below are fixtures shaped on the 29/10 replay (skill-vp/essai-auditfix-29-10)."""
import json, pathlib, shutil, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import study_family as SF, cross_source as CS, validate_card as V   # noqa: E402,E401


def report(body, biblio):
    return ('# R\n## Executive Summary\nS.\n## Introduction\nI.\n## Main Analysis\n### Finding 1 — x\n' + body + '\n## Synthesis & Insights\nS.\n'
            '## Limitations & Caveats\nL.\n## Recommendations\nR.\n## Bibliography\n' + biblio + '\n## Methodology Appendix\nM.\n')


def fam(sources, biblio=''):
    return SF.families({'sources': sources}, report('x', biblio) if biblio else '')


def same(f, a, b): return f['family'][a] == f['family'][b]


class T(unittest.TestCase):
    def test_identifier_links(self):
        f = fam({'S1': {'arxiv': '2301.00001v2', 'title': 'A'}, 'S2': {'doi': '10.48550/arXiv.2301.00001', 'title': 'B'},
                 'S3': {'doi': '10.1145/3555.1', 'title': 'C'}, 'S4': {'doi': '10.1145/9999.2', 'title': 'D'}},
                '[1] Smith et al. A. 2023. arxiv:2301.00001.\n[2] Smith et al. B. 2023. doi:10.48550/arXiv.2301.00001.\n'
                '[3] Smith et al. C, ACM. 2024. doi:10.1145/3555.1, also arXiv:2301.00001.\n[4] Doe et al. D. 2024. https://doi.org/10.1145/9999.2\n')
        self.assertTrue(same(f, 'S1', 'S2')); self.assertTrue(same(f, 'S1', 'S3')); self.assertFalse(same(f, 'S1', 'S4'))
        self.assertEqual((f['entries'], f['studies']), (4, 2))
        self.assertEqual({l['signal'] for l in f['groups'][0]['links']}, {'identifier'})

    def test_relation_and_registry(self):
        f = fam({'S1': {'doi': '10.1101/2020.01.01.1', 'title': 'Early preprint', 'relation': {'is-preprint-of': [{'id': '10.1000/j.2', 'id-type': 'doi'}]}},
                 'S2': {'doi': '10.1000/J.2', 'title': 'Final paper'},
                 'S3': {'pmid': '111', 'title': 'Effect of X on Y: a randomised trial (NCT01234567)'},
                 'S4': {'nct': 'NCT01234567', 'title': 'Registry record of the X trial'},
                 'S5': {'pmid': '222', 'title': 'Another trial (ISRCTN12345678)'},
                 'S6': {'doi': '10.1000/k.3', 'title': 'Version two', 'related': ['doi:10.1000/k.4']}, 'S7': {'doi': '10.1000/k.4', 'title': 'Version one'}})
        self.assertTrue(same(f, 'S1', 'S2')); self.assertTrue(same(f, 'S3', 'S4')); self.assertFalse(same(f, 'S3', 'S5')); self.assertTrue(same(f, 'S6', 'S7'))
        sig = {(l['a'], l['b']): l['signal'] for g in f['groups'] for l in g['links']}
        self.assertEqual((sig[('S1', 'S2')], sig[('S3', 'S4')], sig[('S6', 'S7')]), ('relation', 'registry', 'relation'))
        r = fam({'S1': {'doi': '10.1/a', 'title': 'x', 'relation': {'cites': [{'id': '10.1/b', 'id-type': 'doi'}]}}, 'S2': {'doi': '10.1/b', 'title': 'y'}})
        self.assertFalse(same(r, 'S1', 'S2'))                                     # a citation is not a version

    def test_title_and_author(self):
        src = {'S1': {'pmid': '28202713', 'title': 'Vitamin D supplementation to prevent acute respiratory tract infections: systematic review and meta-analysis of individual participant data'},
               'S2': {'pmid': '30675873', 'title': 'Vitamin D supplementation to prevent acute respiratory infections: individual participant data meta-analysis (Health Technology Assessment)'},
               'S3': {'pmid': '33798465', 'title': 'Vitamin D supplementation to prevent acute respiratory infections: systematic review and meta-analysis of aggregate data'},
               'S4': {'pmid': '30646030', 'title': 'Intermittent vs continuous energy restriction and glycaemic control in type 2 diabetes, 12-month randomised noninferiority trial'},
               'S5': {'pmid': '30902672', 'title': 'Intermittent vs continuous energy restriction in type 2 diabetes, 24-month follow-up of the randomised trial'},
               'S6': {'pmid': '27000000', 'title': 'Intermittent vs continuous energy restriction in type 2 diabetes, 12-week pilot randomised trial'}}
        bib = ('[1] Martineau et al. T. BMJ. 2017. pmid:28202713.\n[2] Martineau AR, Jolliffe DA. T. HTA. 2019. pmid:30675873.\n'
               '[3] Jolliffe et al. T. 2021. pmid:33798465.\n[4] Carter et al. T. 2018. pmid:30646030.\n[5] Carter S, Clifton PM. T. 2019. pmid:30902672.\n'
               '[6] Carter et al. T. 2016. pmid:27000000.\n')
        f = fam(src, bib)
        self.assertTrue(same(f, 'S1', 'S2')); self.assertFalse(same(f, 'S1', 'S3')); self.assertTrue(same(f, 'S4', 'S5')); self.assertFalse(same(f, 'S4', 'S6'))
        self.assertFalse(same(f, 'S5', 'S6'))                                     # "pilot": a separate study by design
        f = fam(src, bib.replace('2019. pmid:30675873', '2023. pmid:30675873'))
        self.assertFalse(same(f, 'S1', 'S2'))                                     # year gap above year_gap_max
        self.assertEqual(SF.first_author('Martineau AR, Jolliffe DA. Title'), 'martineau'); self.assertEqual(SF.first_author('A. R. Martineau, x'), 'martineau')
        self.assertIsNone(SF.first_author('Local document, "W-7 field trial"')); self.assertIsNone(SF.first_author('doi:10.1/x. Title'))

    def test_not_linked(self):
        f = fam({'S1': {'arxiv': '2508.06600', 'title': 'BrowseComp-Plus'}, 'S2': {'arxiv': '2504.12516', 'title': 'BrowseComp'},
                 'S3': {'ecli': 'ECLI:FR:CECHR:2023:463487', 'title': "Conseil d'Etat, decision n° 463487, 20 April 2023"},
                 'S4': {'ecli': 'ECLI:FR:CECHR:2023:464642', 'title': "Conseil d'Etat, decision n° 464642, 20 December 2023"},
                 'S5': {'local': 'docs/r12-a.md@abc', 'title': 'R-12 field trial 2024, coastal saline site'},
                 'S6': {'local': 'docs/r12-b.md@abc', 'title': 'R-12 field trial 2024, non-saline site'},
                 'S7': {'arxiv': '2206.07682', 'title': 'Emergent Abilities of Large Language Models'},
                 'S8': {'arxiv': '2304.15004', 'title': 'Are Emergent Abilities of Large Language Models a Mirage?'}},
                "[1] Chen et al. BrowseComp-Plus. 2025.\n[2] Wei et al. BrowseComp. 2025.\n[3] Conseil d'Etat. Decision 463487. 2023.\n"
                "[4] Conseil d'Etat. Decision 464642. 2023.\n[5] Local document, \"R-12\". 2025.\n[6] Local document, \"R-12\". 2025.\n"
                "[7] arXiv:2206.07682. Emergent Abilities of Large Language Models. 2022.\n[8] Schaeffer et al. Mirage. 2023.\n")
        self.assertEqual(f['studies'], 8, f['groups'])

    def test_disabled(self):
        old = dict(SF.CFG); SF.CFG['enabled'] = False
        try: self.assertEqual(fam({'S1': {'doi': '10.1/a', 'title': 'x'}, 'S2': {'doi': '10.1/A', 'title': 'y'}})['studies'], 2)
        finally: SF.CFG.clear(); SF.CFG.update(old)

    def test_check_14_counts_studies(self):
        fmap = {1: 'F1', 2: 'F1', 3: 'F2'}
        bib = '[1] A. 2020. doi:10.1/a.\n[2] A. 2021. doi:10.1/b.\n[3] C. 2022. doi:10.1/c.\n'
        flagged = lambda body, f=fmap: [x['sentence'] for x in CS.flagged(report(body, bib), families=f)]
        s = 'The largest trial reports 62.8 % [1][2].'
        self.assertEqual(flagged(s, None), []); self.assertEqual(flagged(s), [s])
        x = CS.flagged(report(s, bib), families=fmap)[0]; self.assertTrue(x['same_study']); self.assertEqual(x['studies'], 1)
        s = 'Three trials agree on a null effect [1][2][3].'
        self.assertEqual(flagged(s, None), []); self.assertEqual(flagged(s), [s])
        for ok in ['Two trials agree on a null effect [1][2][3].', 'Fewer than ten sources carry this report, all from one team [1][2][3].',
                   'Across the trials, the effect is null [1][2][3].', 'The trial reports 62.8 % at 12 and 24 months [1][2].']:
            self.assertEqual(flagged(ok), [], ok)
        pb = CS.problems(report('The largest trial reports 62.8 % [1][2].', bib), families=fmap)
        self.assertTrue(any('versions of one study' in p for p in pb), pb)

    def test_validate_card_reads_the_card(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        try:
            card = {'card_id': 'x', 'question': 'q', 'claims': [], 'sources': {
                'S1': {'arxiv': '2301.00001', 'title': 'Retrieval helps'}, 'S2': {'doi': '10.48550/arXiv.2301.00001v3', 'title': 'Retrieval helps (v3)'},
                'S3': {'doi': '10.1/c', 'title': 'Other'}}}
            (tmp / 'card.json').write_text(json.dumps(card))
            (tmp / 'REPORT.md').write_text(report('The largest gain is reported by Lee [1][2]. Lee and Kim differ [1][3].',
                                                  '[1] Lee et al. Retrieval helps. 2023. arxiv:2301.00001.\n[2] Lee et al. Retrieval helps. 2023. doi:10.48550/arXiv.2301.00001v3.\n[3] Kim. Other. 2023. doi:10.1/c.\n'))
            pb = [p for p in V.problems(tmp) if p.startswith('14 ')]
            self.assertEqual(len(pb), 2, pb); self.assertIn('[1][2]', pb[1]); self.assertIn('versions of one study', pb[1])
            out = SF.of_dir(tmp); self.assertEqual((out['entries'], out['studies']), (3, 2))
        finally: shutil.rmtree(tmp)


if __name__ == '__main__':
    unittest.main()
