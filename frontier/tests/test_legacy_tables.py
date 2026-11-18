# SPDX-License-Identifier: Apache-2.0
"""Read contracts compared with the untouched local base, before fixing round 3."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from .helpers import FRONTIER, TempCase, load_tool, read_json, run_tool, write_json
from .test_am1_catalogue import answer

BASE = FRONTIER.parents[1] / 'base' / 'frontier' / 'tools'
OLD12 = 'question note id annee titre methode capacite entree_sortie resultat verif ampleur code'.split()
NEW12 = 'question relevance id year title method capability input_output result verification scale code'.split()
OLD_EXTRA = 'score donnees transposable autre_usage forme verifiable effort'.split()
NEW_EXTRA = 'score data_availability transferability other_uses form_score verifiability effort'.split()
RENAME = dict(zip(OLD12 + OLD_EXTRA + ['liste', 'sujet'], NEW12 + NEW_EXTRA + ['list', 'subject']))
EFFORT = {'faible': 'low', 'moyen': 'medium', 'fort': 'high'}


def translated(row):
    return {RENAME.get(k, k): EFFORT.get(v, v) if k == 'effort' else v for k, v in row.items()}


def reference(name, common=None):
    spec = importlib.util.spec_from_file_location('round3_base_' + name, BASE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    paths = sys.path[:]
    try:
        with patch.dict(sys.modules, {'common': common} if common else {}):
            spec.loader.exec_module(module)
    finally:
        sys.path[:] = paths
    return module


@unittest.skipUnless(BASE.is_dir(), 'local base oracle not installed')
class BaseReadOracle(TempCase):
    def setUp(self):
        super().setUp()
        self.matter = load_tool('matter')
        self.common = self.matter.common
        self.base_common = reference('common')
        self.base_matter = reference('matter', self.base_common)

    def test_catalogues_case_by_case_against_base(self):
        values = dict(zip(OLD12 + OLD_EXTRA,
                          ['Q1', '3', 'W0', '2024', 'felt wooden tile', 'felt sleeve', 'wooden tile',
                           'felt dimensions', 'gain', 'ok', 'fort', '', '10', '3', '0', '1', '2', '3', 'fort']))
        layouts = [('complete12', OLD12), ('complete19', OLD12 + OLD_EXTRA),
                   ('partial', ['id', 'titre', 'methode', 'capacite', 'entree_sortie']),
                   ('reordered_extra', ['custom', 'titre', 'id', 'methode']), ('id_only', ['id'])]
        for label, oldhead in layouts:
            for generation in ('old', 'new'):
                with self.subTest(layout=label, names=generation):
                    path = self.tmp / 'source.tsv'
                    oracle = self.tmp / 'base.tsv'
                    head = oldhead if generation == 'old' else [RENAME.get(k, k) for k in oldhead]
                    cells = [values.get(k, 'custom value') for k in oldhead]
                    # Normal, short, overlong rows: preserve the base reader's padding/truncation.
                    body = ['\t'.join(cells), '\t'.join(cells[:2]), '\t'.join(cells + ['ignored'])]
                    tail = '\n'.join(['# before', '\t'.join(oldhead), '', '# inside', *body]) + '\n'
                    oracle.write_text(tail)
                    path.write_text(tail.replace('\t'.join(oldhead), '\t'.join(head), 1))
                    before = path.read_bytes()
                    expected = [translated(r) for r in self.base_common.read_tsv(oracle)]
                    err = io.StringIO()
                    with contextlib.redirect_stderr(err):
                        actual = self.common.read_tsv(path)
                        self.assertEqual(actual, expected)
                        self.assertEqual(self.matter.read_catalogue(path), expected)
                        self.assertEqual(load_tool('catalogue').read_rows(path), expected)
                        got = self.matter.optional_entry('catalogue', str(path), 'felt wooden tile dimensions', 'main', 2, {})
                    want = self.base_matter.optional_entry('catalogue', str(oracle), 'felt wooden tile dimensions', 'main', 2, {})
                    self.assertEqual(got['matches'], want['matches'])
                    self.assertEqual(path.read_bytes(), before)
                    self.assertEqual(bool(err.getvalue()), generation == 'old' and any(k != RENAME.get(k, k) for k in oldhead) or 'effort' in oldhead)
                    print('oracle catalogue %s %s: rows and matches = base' % (label, generation))

    def test_indexes_case_by_case_against_base(self):
        values = [{'liste': 'A', 'annee': '2025', 'sujet': 'felt sleeve', 'direction': 'wooden tile', 'source': 'S1'},
                  {'liste': 'B', 'annee': '2024', 'sujet': 'felt sleeve', 'direction': 'wooden tile', 'source': 'S2'}]
        layouts = [('complete', ['liste', 'annee', 'sujet', 'direction', 'source']),
                   ('partial', ['liste', 'sujet', 'direction']), ('no_direction', ['liste', 'sujet']),
                   ('no_list', ['sujet', 'direction']), ('subject_only', ['sujet']),
                   ('neutral_only', ['direction']), ('unknown', ['custom'])]
        for label, oldhead in layouts:
            for generation in ('old', 'new'):
                with self.subTest(layout=label, names=generation):
                    oracle, path = self.tmp / 'base-index.tsv', self.tmp / 'index.tsv'
                    body = ''.join('\t'.join(r.get(k, '') for k in oldhead) + '\n' for r in values)
                    head = oldhead if generation == 'old' else [RENAME.get(k, k) for k in oldhead]
                    oracle.write_text('\t'.join(oldhead) + '\n' + body)
                    path.write_text('\t'.join(head) + '\n' + body)
                    before = path.read_bytes()
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(self.matter.read_directions(path), [translated(r) for r in self.base_matter.read_directions(oracle)])
                        got = self.matter.optional_entry('directions', str(path), 'felt sleeve wooden tile', 'main', 2, {})
                    want = self.base_matter.optional_entry('directions', str(oracle), 'felt sleeve wooden tile', 'main', 2, {})
                    self.assertEqual(got['matches'], [translated(r) for r in want['matches']])
                    self.assertEqual(path.read_bytes(), before)
                    print('oracle index %s %s: rows, A filter and matches = base' % (label, generation))

    def test_mixed_headers_are_clearly_refused_even_without_duplicate(self):
        for head in (['id', 'titre', 'method'], ['liste', 'year', 'direction'],
                     ['id', 'titre', 'title'], ['list', 'liste', 'direction']):
            path = self.tmp / 'mixed.tsv'
            path.write_text('\t'.join(head) + '\na\tb\tc\n')
            before = path.read_bytes()
            for reader in (self.common.read_tsv, self.matter.read_catalogue, self.matter.read_directions):
                with self.subTest(head=head, reader=reader.__name__), self.assertRaisesRegex(ValueError, '(?i)mixed.*header|header.*mixed'):
                    reader(path)
            self.assertEqual(path.read_bytes(), before)
        result = run_tool('matter', 'optional', self.work('valid_novp'), env={**os.environ, 'FRONTIER_CATALOGUE': str(path)})
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('mixed old/current table header', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_update_reads_partial_table_without_rewriting_it(self):
        cat = load_tool('catalogue')
        path = self.tmp / 'partial.tsv'
        path.write_text('# keep here\nid\ttitre\nW0\tfelt sleeve\n\n# keep there\n')
        before = path.read_bytes()
        write_json(cat.meta_path(path), {'domain': 'test', 'queries': ['felt'], 'updated': '2025-01-01'})
        args = types.SimpleNamespace(catalogue=str(path), vp=None, T='2026-01-01', work=None)
        with patch.object(cat, 'find_vp_or_fail', return_value=self.tmp), patch.object(cat, 'gather', return_value=[{'id': 'W0'}]), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cat.cmd_update(args), 0)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(read_json(cat.meta_path(path))['updated'], '2026-01-01')


class CatalogueWriteOracle(TempCase):
    def test_ingest_padding_and_comments_keep_base_semantics(self):
        cat = load_tool('catalogue')
        path = self.tmp / 'old.tsv'
        cells = ['Q1', '3', 'W0', '2024', 'felt\x85sleeve', 'sleeve', 'tile', 'input', 'gain', 'ok', 'fort', '']
        path.write_text('# before\n\n' + '\t'.join(OLD12) + '\n# middle\n' + '\t'.join(cells[:3]) + '\n\n' +
                        '\t'.join(cells + ['ignored']) + '\n# after\n')
        columns, rows = cat.read_table(path)
        self.assertEqual(rows[0], dict(zip(NEW12, cells[:3] + [''] * 9)))
        self.assertEqual(rows[1], dict(zip(NEW12, cells)))
        expected = '# before\n\n' + '\t'.join(NEW12) + '\n# middle\n' + '\t'.join(cells[:3] + [''] * 9) + '\n\n' + '\t'.join(cells) + '\n# after\n'
        self.assertEqual(cat.table_body(path, columns, rows), expected)
        self.assertTrue(any('cells' in p for p in cat.check_file(path)))
        batch, answers = self.tmp / 'batch.json', self.tmp / 'answers.json'
        write_json(batch, {'works': [{'id': 'openalex:W1', 'title': 'new title', 'year': 2025}]})
        write_json(answers, [answer('openalex:W1')])
        write_json(cat.meta_path(path), {'question': 'Q1', 'rows': 2})
        args = types.SimpleNamespace(catalogue=str(path), batch=str(batch), answers=str(answers))
        self.assertEqual(cat.cmd_ingest(args), 0)
        self.assertTrue(path.read_text().startswith(expected))
        self.assertEqual(cat.read_rows(path)[-1]['id'], 'openalex:W1')
        self.assertEqual(read_json(cat.meta_path(path))['rows'], 3)

    def test_only_ingest_and_check_require_complete_header(self):
        cat = load_tool('catalogue')
        for head in ('id\ttitre', 'id\ttitle', 'custom\ttitle\tid'):
            path = self.tmp / 'partial.tsv'
            path.write_text(head + '\n')
            with self.assertRaisesRegex(ValueError, 'complete'):
                cat.read_table(path)
            self.assertTrue(any('header' in p for p in cat.check_file(path)))
