# SPDX-License-Identifier: Apache-2.0
"""AM80-AM87: the optional catalogue tool (create, update, ingest, check), mechanical implementability score."""
import json

from .am1_common import AM, load_tool, read_json, run_tool, write_json
from .helpers import FIXTURES

LAB = FIXTURES / 'catalogue' / 'lab_extract.tsv'
COLS12 = ['question', 'note', 'id', 'annee', 'titre', 'methode', 'capacite', 'entree_sortie', 'resultat', 'verif',
          'ampleur', 'code']
EXTRA = ['score', 'donnees', 'transposable', 'autre_usage', 'forme', 'verifiable', 'effort']


def works(*rows):
    return {"index_total": len(rows), "results": [dict(id=i, title=t, year=y, date=d, abstract='Abstract of ' + t)
                                                  for i, t, y, d in rows]}


W = [('openalex:W1', 'Synthetic felt sleeve thickness comparison', 2024, '2024-05-01'),
     ('openalex:W2', 'Synthetic paper cradle corner patterns', 2025, '2025-03-10'),
     ('openalex:W3', 'Synthetic washable wooden tile sleeves', 2026, '2026-02-01'),
     ('openalex:W4', 'Synthetic tile inspection agreement intervals', 2026, '2026-09-09'),
     ('openalex:W5', 'Synthetic paper folding workshop pilot', 2023, None)]


def answer(wid, **over):
    a = {"id": wid, "note": 3, "methode": "Method of " + wid, "capacite": "protect wooden tiles using felt sleeves",
         "entree_sortie": "tile dimensions to sleeve sizes", "resultat": "gain of 3 percent", "verif": "ok", "ampleur": "fort",
         "code": "https://github.com/acme/" + wid.split(':')[1].lower(), "donnees": 3, "transposable": 3,
         "autre_usage": 1, "form": "code", "verifiable": 3, "effort": "faible"}
    a.update(over)
    return a


class ScoreTest(AM):
    def setUp(self):
        super().setUp()
        self.cat = load_tool('catalogue')

    def test_am80_score_vectors(self):
        s = self.cat.score
        self.assertEqual(s(3, 0, 2, 3, 3, 'faible'), 14)
        self.assertEqual(s(1, 3, 0, 1, 0, 'fort'), 5)
        self.assertEqual(s(0, 2, 1, 2, 2, 'moyen'), 8)
        self.assertEqual(s(2, 2, 0, 0, 0, 'fort'), 2)

    def test_am80_english_effort_and_bounds(self):
        self.assertEqual(self.cat.score(3, 0, 2, 3, 3, 'low'), 14)
        for bad in ((4, 0, 0, 0, 0, 'faible'), (0, 0, 3, 0, 0, 'faible'), (0, 0, 0, 4, 0, 'faible'),
                    (0, 0, 0, 0, 0, 'huge')):
            with self.assertRaises(ValueError):
                self.cat.score(*bad)

    def test_am80_exclusion(self):
        e = self.cat.excluded
        self.assertTrue(e(0, 1))
        self.assertTrue(e(0, 0))
        self.assertFalse(e(0, 2))
        self.assertFalse(e(1, 0))

    def test_am81_forme_is_mechanical(self):
        f = self.cat.forme_from
        self.assertEqual(f('https://github.com/acme/x', 'vague'), 3)
        self.assertEqual(f('https://huggingface.co/acme/x', 'principle'), 3)
        self.assertEqual(f('', 'pseudocode'), 2)
        self.assertEqual(f('', 'formula'), 2)
        self.assertEqual(f('', 'principle'), 1)
        self.assertEqual(f('', 'vague'), 0)
        self.assertEqual(f('https://example.org/paper.pdf', 'principle'), 1)
        with self.assertRaises(ValueError):
            f('', 'weird')

    def test_am87_lab_file_is_read(self):
        rows = self.cat.read_rows(LAB)
        self.assertEqual([r['id'] for r in rows], ['W4416453785', 'W4403795293'])
        self.assertEqual(rows[0]['methode'], 'SWE-Dev')
        self.assertNotIn('score', rows[0])


class CatalogueFlowTest(AM):
    def setUp(self):
        super().setUp()
        self.cat = load_tool('catalogue')
        self.set_works(W)
        self.out = self.tmp / 'cat'
        self.tsv = self.out / 'catalogue.tsv'
        self.meta = self.out / 'catalogue.meta.json'

    def set_works(self, rows):
        self.vp = self.fake_vp({"search-openalex|*": works(*rows)})

    def create(self, T='2026-11-14', per_batch='2'):
        return run_tool('catalogue', 'create', '--domain', 'tile packaging', '--out', self.out, '--vp', self.vp,
                        '--T', T, '--query', 'sleeve thickness', '--per-batch', per_batch, '--question', 'Q1')

    def batch(self, n):
        return self.out / 'batches' / ('batch-%03d.json' % n)

    def write_answers(self, n, *answers):
        write_json(self.out / 'batches' / ('batch-%03d.answers.json' % n), list(answers))

    def ingest(self, n):
        return run_tool('catalogue', 'ingest', '--catalogue', self.tsv, '--batch', self.batch(n))

    def test_am82_create(self):
        r = self.create()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        head = self.tsv.read_text(encoding='utf-8').splitlines()
        self.assertEqual(head, ['\t'.join(COLS12 + EXTRA)])
        meta = read_json(self.meta)
        self.assertEqual((meta['domain'], meta['rows'], meta['updated']), ('tile packaging', 0, None))
        self.assertEqual(meta['queries'], ['sleeve thickness'])
        self.assertEqual(sorted(p.name for p in (self.out / 'batches').glob('batch-*.json') if 'answers' not in p.name),
                         ['batch-001.json', 'batch-002.json', 'batch-003.json'])
        b = read_json(self.batch(1))
        self.assertEqual([w['id'] for w in b['works']], ['openalex:W1', 'openalex:W2'])
        for w in b['works']:
            for k in ('id', 'title', 'year', 'abstract'):
                self.assertIn(k, w)
        self.assertIn('answers', b)
        calls = self.fake_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['argv'][calls[0]['argv'].index('--T') + 1], '2026-11-14')

    def test_am82_no_local_copy_of_openalex(self):
        src = (load_tool('catalogue').__file__)
        text = open(src, encoding='utf-8').read()
        for bad in ('urllib', 'socket', 'requests', 'snapshot', 'api.openalex.org'):
            self.assertNotIn(bad, text)

    def test_am83_ingest_writes_rows_with_score(self):
        self.create()
        self.write_answers(1, answer('openalex:W1'), answer('openalex:W2', donnees=0, transposable=1))
        r = self.ingest(1)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = self.tsv.read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines), 2)                      # header + W1; W2 is excluded by the grid
        row = dict(zip(COLS12 + EXTRA, lines[1].split('\t')))
        self.assertEqual((row['id'], row['annee'], row['titre'], row['question']),
                         ('openalex:W1', '2024', 'Synthetic felt sleeve thickness comparison', 'Q1'))
        self.assertEqual(row['score'], '13')
        self.assertEqual(row['forme'], '3')
        meta = read_json(self.meta)
        self.assertEqual((meta['rows'], meta['excluded']), (1, 1))
        self.assertEqual(self.cat.read_rows(self.tsv)[0]['score'], '13')

    def test_am83_one_error_writes_nothing(self):
        self.create()
        before = self.tsv.read_text(encoding='utf-8')
        cases = [
            answer('openalex:W9'),                                   # not in the batch
            answer('openalex:W1', effort='huge'),                    # not in the enumeration
            answer('openalex:W1', methode='has a\ttab'),             # TSV-unsafe
            answer('openalex:W1', capacite='has a\nnewline'),
            answer('openalex:W1', donnees=7),
            answer('openalex:W1', form='weird', code=''),
            answer('openalex:W1', titre='typed by hand'),            # title comes from the batch, never typed
        ]
        for bad in cases:
            self.write_answers(1, answer('openalex:W2'), bad)
            r = self.ingest(1)
            self.assertEqual(r.returncode, 1, (bad, r.stdout, r.stderr))
            self.assertEqual(self.tsv.read_text(encoding='utf-8'), before)

    def test_am83_duplicate_ids(self):
        self.create()
        self.write_answers(1, answer('openalex:W1'), answer('openalex:W1'))
        self.assertEqual(self.ingest(1).returncode, 1)
        self.write_answers(1, answer('openalex:W1'), answer('openalex:W2'))
        self.assertEqual(self.ingest(1).returncode, 0)
        self.assertEqual(self.ingest(1).returncode, 1)           # the same batch again: ids already in the catalogue

    def absorb_all(self):
        for n, ids in ((1, ('W1', 'W2')), (2, ('W3', 'W4')), (3, ('W5',))):
            self.write_answers(n, *[answer('openalex:' + i) for i in ids])
            r = self.ingest(n)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_am85_updated_moves_only_when_all_batches_absorbed(self):
        self.create()
        self.write_answers(1, answer('openalex:W1'), answer('openalex:W2'))
        self.ingest(1)
        self.assertIsNone(read_json(self.meta)['updated'])
        self.assertEqual(len(read_json(self.meta)['pending']['batches']), 2)
        for n, ids in ((2, ('W3', 'W4')), (3, ('W5',))):
            self.write_answers(n, *[answer('openalex:' + i) for i in ids])
            self.ingest(n)
        meta = read_json(self.meta)
        self.assertEqual(meta['updated'], '2026-11-14')
        self.assertFalse(meta['pending']['batches'])

    def update(self, T):
        return run_tool('catalogue', 'update', '--catalogue', self.tsv, '--vp', self.vp, '--T', T)

    def test_am84_update_is_incremental(self):
        self.create()
        self.absorb_all()
        self.set_works(W + [('openalex:W6', 'A new method for rank targets', 2026, '2026-12-01'),
                            ('openalex:W7', 'Another new ranking study', 2027, None)])
        r = self.update('2026-12-31')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        b = read_json(self.batch(4))
        self.assertEqual([w['id'] for w in b['works']], ['openalex:W6', 'openalex:W7'])
        self.assertFalse(self.batch(5).exists())
        meta = read_json(self.meta)
        self.assertEqual(meta['updated'], '2026-11-14')           # unchanged until the batch is absorbed
        self.write_answers(4, answer('openalex:W6'), answer('openalex:W7'))
        self.assertEqual(self.ingest(4).returncode, 0)
        self.assertEqual(read_json(self.meta)['updated'], '2026-12-31')
        self.assertEqual(len(self.tsv.read_text(encoding='utf-8').splitlines()), 8)

    def test_am84_update_with_nothing_new(self):
        self.create()
        self.absorb_all()
        r = self.update('2026-12-31')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('no new work', r.stdout)
        self.assertFalse(self.batch(4).exists())
        self.assertEqual(read_json(self.meta)['updated'], '2026-12-31')

    def test_am84_update_refuses_pending_batches(self):
        self.create()
        r = self.update('2026-12-31')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('pending', r.stderr)

    def test_am84_update_uses_the_stored_queries(self):
        self.create()
        self.absorb_all()
        self.update('2026-12-31')
        qs = [c['argv'] for c in self.fake_calls()]
        self.assertEqual(len(qs), 2)
        for q in qs:
            self.assertEqual(q[q.index('search-openalex') + 1], 'tile packaging sleeve thickness')

    def test_am86_check(self):
        self.create()
        self.absorb_all()
        r = run_tool('catalogue', 'check', '--catalogue', self.tsv)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = self.tsv.read_text(encoding='utf-8').splitlines()
        cols = lines[1].split('\t')
        cols[12] = '14'
        tampered = [lines[0], '\t'.join(cols)] + lines[2:]
        self.tsv.write_text('\n'.join(tampered) + '\n', encoding='utf-8')
        r = run_tool('catalogue', 'check', '--catalogue', self.tsv)
        self.assertEqual(r.returncode, 1)
        self.assertIn('score', r.stdout)
        # a different header, a duplicate id, an excluded row written
        self.tsv.write_text('\n'.join(['id\tx'] + lines[1:]) + '\n', encoding='utf-8')
        self.assertEqual(run_tool('catalogue', 'check', '--catalogue', self.tsv).returncode, 1)
        self.tsv.write_text('\n'.join(lines + [lines[1]]) + '\n', encoding='utf-8')
        self.assertEqual(run_tool('catalogue', 'check', '--catalogue', self.tsv).returncode, 1)
        c = lines[1].split('\t')
        c[2], c[13], c[14] = 'openalex:W99', '0', '1'
        c[12] = str(self.cat.score(0, 1, int(c[15]), int(c[16]), int(c[17]), c[18]))
        self.tsv.write_text('\n'.join(lines + ['\t'.join(c)]) + '\n', encoding='utf-8')
        r = run_tool('catalogue', 'check', '--catalogue', self.tsv)
        self.assertEqual(r.returncode, 1)
        self.assertIn('exclu', r.stdout)

    def test_am86_check_accepts_the_lab_format(self):
        r = run_tool('catalogue', 'check', '--catalogue', LAB)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_am87_frontier_never_needs_the_catalogue(self):
        self.assertClean()
        self.assertEqual(self.card().returncode, 0)
