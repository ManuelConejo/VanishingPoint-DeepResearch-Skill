# SPDX-License-Identifier: Apache-2.0
"""Round 2 input compatibility oracle, written before the implementation."""
import contextlib
import io
from unittest.mock import patch

from .am1_common import AM, VP, load_tool, read_json, run_tool, write_json
from .test_am1_catalogue import answer

OLD12 = 'question note id annee titre methode capacite entree_sortie resultat verif ampleur code'.split()
OLD_EXTRA = 'score donnees transposable autre_usage forme verifiable effort'.split()
OLD_ANSWER = dict(zip('relevance method capability input_output result verification scale data_availability transferability other_uses verifiability'.split(),
                      'note methode capacite entree_sortie resultat verif ampleur donnees transposable autre_usage verifiable'.split()))


class Round2Compatibility(AM):
    def catalogue(self, extra=True):
        p = self.tmp / 'catalogue.tsv'
        cells = ['Q1', '3', 'W0', '2024', 'felt wooden tile', 'felt sleeve', 'wooden tile', 'felt dimensions', 'gain', 'ok', 'fort', '']
        p.write_text('\t'.join(OLD12 + (OLD_EXTRA if extra else [])) + '\n' +
                     '\t'.join(cells + (['10', '3', '0', '1', '2', '3', 'fort'] if extra else [])) + '\n')
        return p

    def test_legacy_catalogue_scores_and_answers(self):
        cat = load_tool('catalogue')
        for old, new, expected in [('faible', 'low', 14), ('moyen', 'medium', 13), ('fort', 'high', 12)]:
            with self.subTest(old=old):
                self.assertEqual(cat.score(3, 0, 2, 3, 3, old), expected)
                self.assertEqual(cat.score(3, 0, 2, 3, 3, new), expected)
        for extra in (False, True):
            p = self.catalogue(extra)
            self.assertEqual(cat.check_file(p), [])
            row = cat.read_rows(p)[0]
            self.assertEqual(row['title'], 'felt wooden tile')
            self.assertEqual(row['scale'], 'fort')  # free text is never translated
            if extra:
                self.assertEqual(row['effort'], 'high')
        rec = {OLD_ANSWER.get(k, k): v for k, v in answer('openalex:W1').items()}
        rec['effort'] = 'faible'
        self.assertEqual(cat.validate_answers([rec], {'works': [{'id': 'openalex:W1'}]}, set()), [])

    def test_ingest_migrates_entire_old_table_and_refuses_unknown_or_mixed_header(self):
        cat = load_tool('catalogue')
        for extra in (False, True):
            p = self.catalogue(extra)
            meta = {'question': 'Q1', 'rows': 1, 'pending': {'T': '2026-11-14', 'batches': ['batch.json']}}
            write_json(cat.meta_path(p), meta)
            bp = self.tmp / 'batch.json'
            write_json(bp, {'works': [{'id': 'openalex:W1', 'title': 'new title', 'year': 2025}]})
            ap = self.tmp / 'answers.json'
            rec = {OLD_ANSWER.get(k, k): v for k, v in answer('openalex:W1').items()}
            rec['effort'] = 'faible'
            write_json(ap, [rec])
            r = run_tool('catalogue', 'ingest', '--catalogue', p, '--batch', bp, '--answers', ap)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(p.read_text().splitlines()[0].split('\t'), cat.COLS12 + (cat.EXTRA if extra else []))
            self.assertEqual(cat.check_file(p), [])
            rows = cat.read_rows(p)
            self.assertEqual([row['id'] for row in rows], ['W0', 'openalex:W1'])
            self.assertEqual(rows[0]['scale'], 'fort')
            if extra:
                self.assertEqual(rows[1]['effort'], 'low')
        for head in ['id\tunknown', '\t'.join(['question', 'relevance'] + OLD12[2:])]:
            p.write_text(head + '\n')
            before = p.read_bytes(), cat.meta_path(p).read_bytes()
            for command in ('ingest', 'check'):
                args = ['--batch', bp, '--answers', ap] if command == 'ingest' else []
                r = run_tool('catalogue', command, '--catalogue', p, *args)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn('header', (r.stdout + r.stderr).lower())
            self.assertEqual((p.read_bytes(), cat.meta_path(p).read_bytes()), before)

    def test_old_sources_and_material_reach_check_without_mat_catalogue_error(self):
        matter = load_tool('matter')
        cat = self.catalogue()
        idx = self.tmp / 'directions.tsv'
        idx.write_text('liste\tannee\tsujet\tdirection\tsource\nA\t2025\tfelt sleeve\twooden tile\tS1\n'
                       'B\t2024\tfelt sleeve\twooden tile\tS2\n')
        self.assertEqual([r['year'] for r in matter.read_directions(idx)], ['2025'])
        c = matter.optional_entry('catalogue', str(cat), 'felt wooden tile dimensions', 'main', 2, {})
        d = matter.optional_entry('directions', str(idx), 'felt sleeve wooden tile', 'main', 2, {})
        self.assertEqual([r['id'] for r in c['matches']], ['W0'])
        self.assertEqual([r['source'] for r in d['matches']], ['S1'])
        w = self.work(VP)
        write_json(w / 'material.json', {'version': 1, 'items': [], 'searched': [], 'optional_sources': {
            'catalogue': {'status': 'used', 'path': str(cat), 'matches': [{'id': 'W0', 'titre': 'felt wooden tile', 'methode': 'felt sleeve'}]},
            'directions': {'status': 'used', 'path': str(idx), 'matches': [
                {'for': 'main', 'direction': 'wooden tile', 'annee': '2025', 'liste': 'A', 'sujet': 'felt sleeve'}]}}})
        r = run_tool('check', w)
        self.assertNotIn('[MAT-CATALOGUE]', r.stdout + r.stderr)
        mat = matter.load_material(w)
        matter.save_material(w, mat)
        saved = read_json(w / 'material.json')['optional_sources']
        self.assertEqual(saved['directions']['matches'][0]['year'], '2025')
        self.assertEqual(saved['catalogue']['matches'][0]['title'], 'felt wooden tile')
        self.assertNotIn('titre', saved['catalogue']['matches'][0])
        # A forged list-B match still fails through the same full checker path.
        mat['optional_sources']['directions']['matches'][0]['year'] = '2024'
        write_json(w / 'material.json', mat)
        r = run_tool('check', w)
        self.assertIn('[MAT-CATALOGUE]', r.stdout + r.stderr)

    def test_tables_warn_and_keep_current_keys_and_free_text(self):
        names = load_tool('input_names')
        expected = dict(zip('note annee titre methode capacite entree_sortie resultat verif ampleur donnees transposable autre_usage forme verifiable liste sujet'.split(),
                            'relevance year title method capability input_output result verification scale data_availability transferability other_uses form_score verifiability list subject'.split()))
        self.assertEqual(names.FIELD_ALIASES, expected)
        for old, new in expected.items():
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(names.normalize_fields({old: 'old', new: 'new'}), {new: 'new'})
            self.assertEqual(err.getvalue().splitlines(), ['deprecated name, use %s (%s)' % (new, old)])
        self.assertEqual(names.normalize_fields({'scale': 'fort', 'method': 'donnees'}), {'scale': 'fort', 'method': 'donnees'})
        p = self.tmp / 'bad.tsv'
        p.write_text('unknown\tfield\na\tb\n')
        self.assertEqual(load_tool('matter').read_directions(p), [{'unknown': 'a', 'field': 'b'}])

    def test_catalogue_reader_keeps_base_row_padding_and_truncation(self):
        cat = load_tool('catalogue')
        p = self.tmp / 'reading.tsv'
        header = '\t'.join(cat.COLS12) + '\n'
        p.write_text(header + 'Q1\t3\tW0\n')
        row = cat.read_rows(p)[0]
        self.assertEqual(row['id'], 'W0')
        self.assertEqual(row['code'], '')
        self.assertEqual(set(row), set(cat.COLS12))
        cells = ['Q1', '3', 'W0', '2025', 'title', 'method', 'capability', 'input', 'result', 'ok', 'fort', 'repo']
        p.write_text(header + '\t'.join(cells + ['ignored by the base reader']) + '\n')
        self.assertEqual(cat.read_rows(p), [dict(zip(cat.COLS12, cells))])

    def test_frontier_config_fallback_and_precedence(self):
        common = load_tool('common')
        for raw, expected, warning in [({'tournoi': {'max_debates': 2}}, 2, True),
                                        ({'tournoi': {'max_debates': 2}, 'tournament': {'max_debates': 4}}, 4, True)]:
            err = io.StringIO()
            with patch.object(common, 'read_json', return_value=raw), contextlib.redirect_stderr(err):
                cfg = common.config()
            self.assertEqual(cfg['tournament']['max_debates'], expected)
            self.assertNotIn('tournoi', cfg)
            self.assertEqual('deprecated name, use tournament' in err.getvalue(), warning)
