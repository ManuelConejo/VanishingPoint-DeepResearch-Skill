# SPDX-License-Identifier: Apache-2.0
"""tools/history.py: search and extraction in the local archives of the project (regression specification HI1-HI13)."""
import ast
import contextlib
import io
import socket
import unittest
from pathlib import Path
from unittest import mock

from .helpers import FRONTIER, TOOLS, copy_skill, load_tool, mutate, read_json, run_tool, set_config, write_json
from .hist_common import E_CAPS, HB, INTAKE_TERMS, FOLD_TERM, write_files
import json

from . import hist_common

SOFTFOLD = [dict(FOLD_TERM, **{'for': 'T2'})]


def term(name, *syn, **kw):
    d = {'term': name, 'synonyms': list(syn), 'group': 'idea'}
    d.update(kw)
    return d


class IntakeFieldTest(HB):
    """HI1."""

    def test_absent_and_empty_are_valid(self):
        self.assertEqual(self.problems(self.work('valid_novp')), [])
        mutate(self.work('valid_novp'), 'intake.json', lambda d: d.update(project_dirs=[]))
        self.assertEqual(self.problems(self.work('valid_novp')), [])

    def test_bad_types_refused(self):
        for bad in ('/some/dir', 5, [3], [''], [None]):
            with self.subTest(bad=bad):
                self.fresh()
                mutate(self.work('valid_novp'), 'intake.json', lambda d: d.update(project_dirs=bad))
                probs = self.problems(self.work('valid_novp'))
                self.assertTrue(any(p.startswith(('[SCHEMA]', '[INTAKE]')) and 'project_dirs' in p for p in probs), probs)

    def test_schema_documents_it(self):
        schema = read_json(FRONTIER / 'schemas' / 'intake.json')
        self.assertIn('project_dirs', schema['properties'])
        self.assertNotIn('project_dirs', schema['required'])


class ScanBasicsTest(HB):
    """HI2, HI3."""

    def setUp(self):
        super().setUp()
        self.w = self.tmp / 'w'
        self.w.mkdir()

    def run_scan(self, terms, **kw):
        return self.scan_ok(self.w, 'intake', terms, dirs=[str(self.proj)], **kw)

    def test_finds_term_with_file_line_excerpt(self):
        h = self.run_scan([term('softfold')])
        rel = 'results/test_softfold.md'
        e = self.entry(self.w, rel, 'Verdict : -63')
        self.assertEqual(e['line'], 10)
        self.assertIn('SoftFold', e['excerpt'])
        self.assertLessEqual(len(e['excerpt']), common_cfg()['max_excerpt_chars'])
        self.assertEqual(e['terms'], ['softfold'])
        files = {x['file'] for x in h['entries']}
        self.assertIn('LESSONS.md', files)
        self.assertTrue(all('\\' not in f for f in files))
        ids = [x['id'] for x in h['entries']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i.startswith('E') for i in ids))

    def test_code_identifier_found(self):
        self.run_scan([term('plainfold')])
        e = self.entry(self.w, 'scripts/prepare_cradle.py', '"objective": "plainfold"')
        self.assertEqual(e['line'], 5)
        self.assertIn('objective', e['excerpt'])

    def test_extensions(self):
        d = self.tmp / 'ext'
        write_files(d, {'a.rst': 'zebrafish here\n', 'b.yaml': 'k: zebrafish\n', 'c.yml': 'k: zebrafish\n',
                        'd.json': '{"k": "zebrafish"}\n', 'e.md': 'zebrafish\n', 'f.txt': 'zebrafish\n',
                        'g.py': '# zebrafish\n', 'h.csv': 'zebrafish\n', 'i.toml': 'k = "zebrafish"\n',
                        'j.html': '<p>zebrafish</p>\n', 'k': 'zebrafish\n'})
        r = self.scan(self.w, 'intake', [term('zebrafish')], dirs=[str(d)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(e['file'] for e in self.hist(self.w)['entries']),
                         ['a.rst', 'b.yaml', 'c.yml', 'd.json', 'e.md', 'f.txt', 'g.py'])

    def test_accent_and_case_insensitive(self):
        self.run_scan([term('CAFE')])
        e = self.entry(self.w, 'results/test_softfold.md', 'SoftFold vs PlainFold')
        self.assertEqual(e['line'], 1)

    def test_word_boundaries(self):
        self.run_scan([term('fold')])
        files_lines = {(e['file'], e['line']) for e in self.hist(self.w)['entries']}
        self.assertNotIn(('results/test_softfold.md', 8), files_lines)     # "softfold" is not the word "fold"
        self.assertIn(('LESSONS.md', 5), files_lines)                        # "Soft-Fold" is

    def test_synonyms_and_canonical_term(self):
        self.run_scan([term('soft fold', 'FOLD', 'softfold')])
        e = self.entry(self.w, 'LESSONS.md', 'Soft-Fold')
        self.assertEqual(e['terms'], ['soft fold'])
        e2 = self.entry(self.w, 'results/test_softfold.md', 'Verdict : -63')
        self.assertEqual(e2['terms'], ['soft fold'])
        self.assertIn('SoftFold', e2['matched'])

    def test_french_synonym_with_apostrophe(self):
        self.run_scan([term('tile packing', "protection d'angles")])
        e = self.entry(self.w, 'results/test_softfold.md', "protection d'angles")
        self.assertEqual(e['terms'], ['tile packing'])
        self.assertIn("protection d'angles", e['matched'])

    def test_terms_given_on_the_command_line(self):
        r = run_tool('history', 'scan', self.w, '--label', 'intake', '--term', 'softfold=fold|soft fold',
                     '--project-dir', self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        e = self.entry(self.w, 'research/fold/FOLD_PACKING_SUMMARY.md')
        self.assertEqual(e['terms'], ['softfold'])

    def test_none_found_is_written_and_never_a_proof(self):
        h = self.run_scan([term('zzzznothingzzzz')])
        self.assertEqual(h['entries'], [])
        self.assertIn('not a proof', h['note'])


class IgnoredTest(HB):
    """HI4."""

    def test_ignored_content_never_read(self):
        w = self.tmp / 'w'
        w.mkdir()
        h = self.scan_ok(w, 'intake', [term('softfold')], dirs=[str(self.proj)])
        for e in h['entries']:
            for bad in ('.git/', 'venv/', '.venv/', 'node_modules/', '__pycache__/', 'data/', 'linkdir/', 'results/link.md'):
                self.assertFalse(e['file'].startswith(bad), e['file'])
        skipped = h['scan']['files_skipped']
        self.assertGreaterEqual(skipped.get('binary', 0), 2)         # blob.json and blob.txt hold a NUL byte
        self.assertGreaterEqual(skipped.get('extension', 0), 3)      # model.pkl, prices.csv, conf.toml
        self.assertGreaterEqual(skipped.get('link', 0), 1)
        self.assertGreater(h['scan']['files_scanned'], 4)


class CapsTest(HB):
    """HI5."""

    def skill(self, **hist):
        sk = copy_skill(self.tmp / 'skill')

        def cfg(c):
            c.setdefault('history', {}).update(hist)
        set_config(sk, cfg)
        return sk / 'tools'

    def run_capped(self, **hist):
        w = self.tmp / 'w'
        w.mkdir(exist_ok=True)
        return self.scan_ok(w, 'intake', [term('softfold', 'paper folding')], dirs=[str(self.proj)],
                            tools_dir=self.skill(**hist))

    def test_file_too_large_is_skipped_and_counted(self):
        h = self.run_capped(max_file_bytes=500)
        self.assertNotIn('results/test_softfold.md', {e['file'] for e in h['entries']})
        self.assertGreaterEqual(h['scan']['files_skipped'].get('too_large', 0), 1)

    def test_max_files_stops_the_walk(self):
        h = self.run_capped(max_files=2)
        self.assertTrue(h['scan']['truncated'])
        self.assertEqual(h['scan']['files_scanned'], 2)

    def test_max_total_bytes_stops_the_walk(self):
        h = self.run_capped(max_total_bytes=900)
        self.assertTrue(h['scan']['truncated'])

    def test_max_entries_per_file(self):
        h = self.run_capped(max_entries_per_file=1)
        counts = {}
        for e in h['entries']:
            counts[e['file']] = counts.get(e['file'], 0) + 1
        self.assertTrue(counts and max(counts.values()) == 1)

    def test_not_truncated_by_default(self):
        h = self.run_capped()
        self.assertFalse(h['scan']['truncated'])


class VerdictTest(HB):
    """HI6, HI7, HI8."""

    def setUp(self):
        super().setUp()
        self.w = self.tmp / 'w'
        self.w.mkdir()

    def scan_project(self, terms, **kw):
        return self.scan_ok(self.w, 'intake', terms, dirs=[str(self.proj)], **kw)

    def test_synthetic_case_classed(self):
        self.scan_project([term('softfold')])
        for rel, needle in (('results/test_softfold.md', 'Verdict : -63'), ('LESSONS.md', 'softfold')):
            e = self.entry(self.w, rel, needle)
            self.assertEqual(e['verdict'], 'classed', rel)
            self.assertIn('CLASS' + E_CAPS, e['markers'])
        e = self.entry(self.w, 'results/test_softfold.md', 'Verdict : -63')
        self.assertIn('NE PAS ROUVRIR', e['markers'])

    def test_english_markers_and_block(self):
        self.scan_project([term('corner trimming')])
        e = self.entry(self.w, 'notes/en_summary.txt')
        self.assertEqual(e['verdict'], 'classed')
        self.assertIn('REJECTED', e['markers'])
        self.assertIn('DO NOT REOPEN', e['markers'])

    def test_weak_marker_is_tried_and_bullets_do_not_leak(self):
        self.scan_project([term('paper folding')])
        e = self.entry(self.w, 'LESSONS.md', 'paper folding')
        self.assertEqual(e['verdict'], 'tried')           # the next bullet says CLASSE: another passage
        self.assertIn('test' + hist_common.E_ACUTE, e['markers'])
        s = self.entry(self.w, 'scripts/prepare_cradle.py')
        self.assertEqual(s['verdict'], 'none')
        self.assertEqual(s['markers'], [])

    def test_marker_table(self):
        d = self.tmp / 'mk'
        rows = [
            ('zebra: NON ADOPT\u00c9', 'classed'), ('zebra non adopt\u00e9e', 'classed'), ('zebra: NO-GO', 'classed'),
            ('zebra no go', 'classed'), ('zebra : NE PAS INT\u00c9GRER', 'classed'),
            ('zebra was rejected by the team', 'classed'), ('zebra: Do Not Reopen', 'classed'),
            ('zebra rejet\u00e9', 'classed'), ('zebra CLASSE', 'classed'), ('zebra class\u00e9 sans suite', 'classed'),
            ('zebra : ne jamais re-proposer', 'classed'), ('never re-propose zebra', 'classed'),
            ('zebra verdict: pending', 'tried'), ('zebra was tested twice', 'tried'), ('zebra: already tried here', 'tried'),
            ('zebra d\u00e9j\u00e0 essay\u00e9', 'tried'), ('zebra test\u00e9 en 2023', 'tried'),
            ('zebra is a striped animal', 'none'),
            ("allocation par classe d'actifs : zebra", 'none'), ('the zebra class of animals', 'none'),
        ]
        write_files(d, {'m%02d.md' % i: text + '\n' for i, (text, _) in enumerate(rows)})
        r = self.scan(self.w, 'intake', [term('zebra')], dirs=[str(d)])
        self.assertEqual(r.returncode, 0, r.stderr)
        got = {e['file']: e['verdict'] for e in self.hist(self.w)['entries']}
        for i, (text, want) in enumerate(rows):
            self.assertEqual(got.get('m%02d.md' % i), want, text)

    def test_reopen_condition(self):
        self.scan_project([term('softfold'), term('corner trimming')])
        e = self.entry(self.w, 'results/test_softfold.md', 'Verdict : -63')
        self.assertIn('FOLD_PACKING_SUMMARY', e['reopen_condition'])
        self.assertEqual(e['reopen_line'], 16)
        self.assertIsNone(self.entry(self.w, 'LESSONS.md', 'softfold')['reopen_condition'])
        en = self.entry(self.w, 'notes/en_summary.txt')
        self.assertTrue('triples' in en['reopen_condition'] or '2000' in en['reopen_condition'])

    def test_reopen_markers(self):
        d = self.tmp / 'ro'
        rows = [('zebra CLASSE. Reopen when the budget doubles.', 'budget doubles'),
                ('zebra CLASS\u00c9 ; r\u00e9ouverture si les donn\u00e9es doublent', 'doublent'),
                ('zebra CLASS\u00c9 : rouvrir seulement si le prix baisse', 'prix baisse'),
                ('zebra REJECTED. Condition de r\u00e9ouverture : 3 mois de donnees', '3 mois'),
                ('zebra REJECTED. Reopening condition: new vendor feed', 'vendor feed'),
                ('zebra REJECTED, no way back', None)]
        write_files(d, {'r%d.md' % i: t + '\n' for i, (t, _) in enumerate(rows)})
        self.scan_ok(self.w, 'intake', [term('zebra')], dirs=[str(d)])
        got = {e['file']: e['reopen_condition'] for e in self.hist(self.w)['entries']}
        for i, (text, want) in enumerate(rows):
            if want is None:
                self.assertIsNone(got['r%d.md' % i], text)
            else:
                self.assertIn(want, got['r%d.md' % i], text)

    def test_distant_marker_in_another_block_is_not_a_verdict(self):
        d = self.tmp / 'far'
        write_files(d, {'a.md': '\n'.join(['filler'] * 7 + ['zebra appears here', '', 'other paragraph CLASS\u00c9', '']),
                        'b.md': '\n'.join(['filler'] * 7 + ['zebra appears here', '', 'filler', '']),
                        'near.py': '# CLASS\u00c9\nzebra = 1\n',
                        'far.py': '# CLASS\u00c9\n' + '#\n' * 12 + 'zebra = 1\n'})
        self.scan_ok(self.w, 'intake', [term('zebra')], dirs=[str(d)])
        got = {e['file']: e['verdict'] for e in self.hist(self.w)['entries']}
        self.assertEqual(got['a.md'], 'none')
        self.assertEqual(got['b.md'], 'none')
        self.assertEqual(got['near.py'], 'classed')
        self.assertEqual(got['far.py'], 'none')

    def test_title_or_path_term_lets_the_file_verdict_apply(self):
        self.scan_project([term('softfold')])
        e = self.entry(self.w, 'results/test_softfold.md', '| softfold |')     # a table row, far from the marker
        self.assertEqual(e['verdict'], 'classed')


class RerunTest(HB):
    """HI10."""

    def setUp(self):
        super().setUp()
        self.w = self.tmp / 'w'
        self.w.mkdir()

    def ids(self):
        return {(e['file'], e['line']): e['id'] for e in self.hist(self.w)['entries']}

    def test_labels_merge_and_ids_are_kept(self):
        self.scan_ok(self.w, 'intake', [term('softfold')], dirs=[str(self.proj)])
        before = self.ids()
        self.scan_ok(self.w, 'tests', [term('corner trimming', **{'for': 'T1'}), term('softfold', **{'for': 'T2'})],
                     dirs=[str(self.proj)])
        h = self.hist(self.w)
        self.assertEqual([q['label'] for q in h['queries']], ['intake', 'tests'])
        after = self.ids()
        for k, v in before.items():
            self.assertEqual(after[k], v)
        self.assertIn('notes/en_summary.txt', {e['file'] for e in h['entries']})
        e = self.entry(self.w, 'results/test_softfold.md', 'Verdict : -63')
        self.assertEqual(sorted(e['labels']), ['intake', 'tests'])
        self.assertEqual(e['for'], ['T2'])

    def test_same_label_replaces_its_query(self):
        self.scan_ok(self.w, 'intake', [term('softfold')], dirs=[str(self.proj)])
        self.scan_ok(self.w, 'tests', [term('corner trimming', **{'for': 'T1'})], dirs=[str(self.proj)])
        h = self.scan_ok(self.w, 'intake', [term('zebrafish')], dirs=[str(self.proj)])
        self.assertEqual([q['label'] for q in h['queries']], ['intake', 'tests'])
        files = {e['file'] for e in h['entries']}
        self.assertEqual(files, {'notes/en_summary.txt'})

    def test_deterministic(self):
        a = self.scan_ok(self.w, 'intake', [term('softfold'), term('plainfold')], dirs=[str(self.proj)])
        b = self.scan_ok(self.w, 'intake', [term('softfold'), term('plainfold')], dirs=[str(self.proj)])
        self.assertEqual(a['entries'], b['entries'])
        self.assertEqual(a['scan'], b['scan'])


class FileFormatTest(HB):
    """HI11, HI13."""

    def setUp(self):
        super().setUp()
        self.w = self.tmp / 'w'
        self.w.mkdir()

    def test_history_json_matches_its_schema(self):
        schema_lite = load_tool('schema_lite')
        self.scan_ok(self.w, 'intake', [term('softfold')], dirs=[str(self.proj)])
        self.scan_ok(self.w, 'tests', [dict(FOLD_TERM, **{'for': 'T2'})], dirs=[str(self.proj)])
        h = self.hist(self.w)
        schema = read_json(FRONTIER / 'schemas' / 'history.json')
        self.assertEqual(schema_lite.validate(h, schema), [])
        self.assertEqual(h['stage'], 'history')
        self.assertRegex(h['generated_utc'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')
        self.assertEqual(h['project_dirs'], [str(self.proj)])

    def test_project_dirs_default_to_the_intake(self):
        work = self.new_work()
        r = run_tool('history', 'scan', work, '--label', 'intake', '--terms-file', self.terms_file([term('softfold')]))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.hist(work)['project_dirs'], [str(self.proj)])
        self.assertTrue(self.entries(work))

    def test_missing_project_dir_refused_and_nothing_written(self):
        r = self.scan(self.w, 'intake', [term('softfold')], dirs=[str(self.tmp / 'does-not-exist')])
        self.assertEqual(r.returncode, 1)
        self.assertFalse((self.w / 'history.json').exists())

    def test_no_project_dir_at_all_is_a_usage_error(self):
        r = self.scan(self.w, 'intake', [term('softfold')])
        self.assertEqual(r.returncode, 2)

    def test_usage_errors(self):
        tf = self.terms_file([term('x')])
        for args in (['scan', self.w, '--label', 'bogus', '--terms-file', tf, '--project-dir', self.proj],
                     ['scan', self.w, '--label', 'intake', '--project-dir', self.proj],
                     ['scan', self.w, '--label', 'intake', '--terms-file', self.tmp / 'nope.json', '--project-dir', self.proj],
                     ['scan', self.tmp / 'no-such-dir', '--label', 'intake', '--terms-file', tf, '--project-dir', self.proj]):
            with self.subTest(args=[str(a) for a in args]):
                self.assertEqual(run_tool('history', *args).returncode, 2)

    def test_for_required_on_tests_and_rebound_labels(self):
        for label in ('tests', 'rebound'):
            with self.subTest(label=label):
                r = self.scan(self.w, label, [term('softfold')], dirs=[str(self.proj)])
                self.assertEqual(r.returncode, 2)
                self.assertIn('for', r.stderr + r.stdout)
                self.assertFalse((self.w / 'history.json').exists())
        r = self.scan(self.w, 'intake', [term('softfold')], dirs=[str(self.proj)])
        self.assertEqual(r.returncode, 0)

    def test_bad_terms_refused(self):
        for bad in ([{'term': ''}], [{'term': 'x', 'synonyms': 'y'}], [{'term': 'x', 'generic': 'yes'}],
                    [{'term': 'x', 'synonyms': [3]}], [], [{'nope': 1}]):
            with self.subTest(bad=bad):
                r = self.scan(self.w, 'intake', bad, dirs=[str(self.proj)])
                self.assertEqual(r.returncode, 2)

    def test_generic_flag_recorded(self):
        self.scan_ok(self.w, 'intake', [term('softfold', generic=True)], dirs=[str(self.proj)])
        q = self.hist(self.w)['queries'][0]
        self.assertTrue(q['terms'][0]['generic'])


class LocalOnlyTest(HB):
    """HI12: the archives never leave the machine."""

    def test_no_network_or_process_modules(self):
        tree = ast.parse((TOOLS / 'history.py').read_text(encoding='utf-8'))
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods.add(node.module.split('.')[0])
        banned = {'socket', 'urllib', 'http', 'ssl', 'subprocess', 'ftplib', 'smtplib', 'requests', 'asyncio',
                  'xmlrpc', 'telnetlib', 'webbrowser', 'multiprocessing', 'ctypes'}
        self.assertEqual(sorted(mods & banned), [])

    def test_scan_works_with_the_network_cut(self):
        w = self.tmp / 'w'
        w.mkdir()

        def boom(*a, **k):
            raise AssertionError('network used')
        with mock.patch.object(socket, 'socket', boom), mock.patch.object(socket, 'create_connection', boom), \
                contextlib.redirect_stdout(io.StringIO()):
            rc = self.history.main(['scan', str(w), '--label', 'intake', '--terms-file',
                                    str(self.terms_file([term('softfold')])), '--project-dir', str(self.proj)])
        self.assertEqual(rc, 0)
        self.assertTrue(self.entries(w))

    def test_help_mentions_local_only(self):
        r = run_tool('history', '--help')
        self.assertEqual(r.returncode, 0)
        self.assertIn('local', r.stdout.lower())


def common_cfg():
    return load_tool('common').config()['history']


class ConfigTest(unittest.TestCase):
    def test_defaults_in_common_and_config_json(self):
        cfg = common_cfg()
        for k in ('max_files', 'max_file_bytes', 'max_total_bytes', 'max_entries_per_file', 'max_excerpt_chars',
                  'window_lines', 'file_verdict_lines', 'leak_shingle_words', 'ignore_dirs', 'extensions'):
            self.assertIn(k, cfg, k)
        for d in ('.git', 'venv', 'node_modules'):
            self.assertIn(d, cfg['ignore_dirs'])
        for e in ('md', 'txt', 'rst', 'py', 'json', 'yaml'):
            self.assertIn(e, cfg['extensions'])
        raw = json.loads((FRONTIER / 'config.json').read_text(encoding='utf-8'))
        self.assertIn('history', raw)
        self.assertGreaterEqual(cfg['max_files'], 100)


if __name__ == '__main__':
    unittest.main()
