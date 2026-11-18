# SPDX-License-Identifier: Apache-2.0
"""Independent public-name oracle, written before the English-name migration."""
import unittest

from .helpers import FRONTIER, TempCase, load_tool, read_json


class EnglishNamesOracle(TempCase):
    def test_tournament_public_paths_and_brand(self):
        self.assertTrue((FRONTIER / 'tools' / 'tournament.py').is_file())
        self.assertTrue((FRONTIER / 'schemas' / 'tournament.json').is_file())
        self.assertTrue((FRONTIER / 'tools' / 'tournoi.py').is_file())
        tool = load_tool('tournament')
        self.assertEqual(tool.JOURNAL, 'tournament_rebound.json')
        self.assertIn('[TOURNAMENT]', tool.summary(self.tmp))

    def test_catalogue_contract(self):
        tool = load_tool('catalogue')
        self.assertEqual(tool.COLS12, ['question', 'relevance', 'id', 'year', 'title', 'method', 'capability',
                                      'input_output', 'result', 'verification', 'scale', 'code'])
        self.assertEqual(tool.EXTRA, ['score', 'data_availability', 'transferability', 'other_uses',
                                     'form_score', 'verifiability', 'effort'])
        self.assertEqual(tool.EFFORT, {'low': 0, 'medium': 1, 'high': 2})
        for effort in ('faible', 'moyen', 'fort'):
            with self.subTest(effort=effort):
                self.assertEqual(tool.score(3, 0, 2, 3, 3, effort),
                                 14 - ('faible', 'moyen', 'fort').index(effort))
        self.assertEqual(tool.score(3, 0, 2, 3, 3, 'low'), 14)
        self.assertEqual(tool.score(0, 2, 1, 2, 2, 'medium'), 8)
        self.assertEqual(tool.form_score_from('', 'formula'), 2)
        rows = tool.read_rows(FRONTIER / 'tests' / 'fixtures' / 'catalogue' / 'lab_extract.tsv')
        self.assertIn('year', rows[0])
        self.assertIn('method', rows[0])
        self.assertNotIn('annee', rows[0])

    def test_directions_contract(self):
        tool = load_tool('matter')
        p = self.tmp / 'directions.tsv'
        p.write_text('list\tyear\tsubject\tdirection\tsource\nA\t2026\tfelt sleeve\twooden tile\tS1\n'
                     'B\t2025\tfelt sleeve\twooden tile\tS2\n', encoding='utf-8')
        matches = tool.optional_entry('directions', str(p), 'felt sleeve wooden tile', 'main', 2, {})['matches']
        self.assertEqual(matches, [{'for': 'main', 'direction': 'wooden tile', 'year': '2026',
                                    'list': 'A', 'subject': 'felt sleeve', 'source': 'S1'}])

    def test_root_config_names(self):
        cfg = read_json(FRONTIER.parent / 'tools' / 'config.json')
        self.assertIn('candidate_reading', cfg)
        self.assertNotIn('possibles', cfg)
        self.assertEqual(cfg['candidate_reading']['journal_pool'], 'candidate_reading')
        self.assertTrue((FRONTIER.parent / 'tools' / 'read_candidates.py').is_file())
        self.assertTrue((FRONTIER.parent / 'tools' / 'sources' / 'administrative_justice.py').is_file())

    def test_existing_material_run_is_read_and_written_with_english_fields(self):
        import json
        tool = load_tool('matter')
        legacy = {'version': 1, 'generated_utc': '2026-11-14T00:00:00Z', 'items': [], 'searched': [],
                  'optional_sources': {'directions': {'status': 'used', 'matches': [
                      {'for': 'main', 'direction': 'tile', 'annee': '2025', 'liste': 'A', 'sujet': 'felt'}]}}}
        (self.tmp / 'material.json').write_text(json.dumps(legacy), encoding='utf-8')
        mat = tool.load_material(self.tmp)
        row = mat['optional_sources']['directions']['matches'][0]
        self.assertEqual(row, {'for': 'main', 'direction': 'tile', 'year': '2025', 'list': 'A', 'subject': 'felt'})
        tool.save_material(self.tmp, mat)
        self.assertEqual(read_json(self.tmp / 'material.json')['optional_sources']['directions']['matches'][0], row)
