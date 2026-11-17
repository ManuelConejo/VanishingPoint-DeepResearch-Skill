# SPDX-License-Identifier: Apache-2.0
"""tools/export_rebound.py: blind export of the three-arm pilot, A Frontier, B model + VP without operators, C model alone
(regression specification RB26, rewritten in round 2: RB32 secret seed, RB33 uniform blind format, RB34 pairing and attestation of the
baselines, RB35 references comparable across arms, RB37 researcher notes written before)."""
import hashlib
import json
import random
import re

from .helpers import load_tool, mutate, read_json, run_tool, write_json
from .rb_common import NOVP, RB, VP

IDEA_KEYS = ['idea_id', 'title', 'statement', 'mechanism', 'hypothesis', 'minimal_test', 'references']


def case_rng(seed_hex, case_id):
    """The documented draw of RB32: random.Random(int(sha256("<seed_hex>:<case_id>"), 16))."""
    return random.Random(int(hashlib.sha256(('%s:%s' % (seed_hex, case_id)).encode('utf-8')).hexdigest(), 16))


class ExportBase(RB):
    def manifest(self):
        return self.fx / 'export_rebound' / 'manifest.json'

    def keyfile(self):
        return self.tmp / 'secret' / 'KEY.json'

    def export(self, out=None, *extra, key=True):
        out = out or self.tmp / 'out'
        args = ['--manifest', self.manifest(), '--out', out]
        if key is True:
            args += ['--key', self.keyfile()]
        r = run_tool('export_rebound', *(args + list(extra)))
        return r, out

    def tree_bytes(self, out):
        return {str(p.relative_to(out)): p.read_bytes() for p in sorted(out.rglob('*')) if p.is_file()}

    def blind(self, out, case='case-01'):
        return read_json(out / 'blind' / (case + '.json'))

    def key(self):
        return read_json(self.keyfile())

    def blob(self, out):
        return '\n'.join(p.read_text(encoding='utf-8') for p in sorted((out / 'blind').iterdir()))

    def fx_export(self, name):
        return self.fx / 'export_rebound' / name


class OutputTest(ExportBase):
    def test_files(self):
        r, out = self.export()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for case in ('case-01', 'case-02'):
            for suffix in ('.json', '.md', '.prior-art-form.json', '.references-to-check.json'):
                self.assertTrue((out / 'blind' / (case + suffix)).exists(), case + suffix)
        self.assertTrue(self.keyfile().exists())
        self.assertEqual(json.loads(r.stdout)['status'], 'ok')

    def test_the_key_is_never_in_the_export_directory(self):
        r, out = self.export()
        self.assertEqual(r.returncode, 0)
        names = [str(p.relative_to(out)) for p in out.rglob('*') if p.is_file()]
        self.assertFalse([n for n in names if 'KEY' in n.upper()], names)

    def test_the_three_arms_share_one_format(self):
        r, out = self.export()
        b = self.blind(out)
        self.assertEqual(len(b['presentations']), 3)
        for p in b['presentations']:
            self.assertEqual(sorted(p), ['ideas', 'label'])
            self.assertEqual(len(p['ideas']), 5)
            for i in p['ideas']:
                self.assertEqual(sorted(i), sorted(IDEA_KEYS))
                self.assertIsInstance(i['references'], list)

    def test_arm_a_content_comes_from_the_rebound_file(self):
        r, out = self.export()
        key = self.key()['cases']['case-01']
        b = self.blind(out)
        src = read_json(self.work(VP) / 'rebound.json')['ideas']
        norm = load_tool('export_rebound').clean
        for p in b['presentations']:
            if key['labels'][p['label']] != 'A':
                continue
            for i in p['ideas']:
                m = key['ideas'][i['idea_id']]
                s = src[m['index']]
                self.assertEqual(m['source_id'], s['id'])
                self.assertEqual(i['title'], norm(s['title'], title=True))
                self.assertEqual(i['mechanism'], norm(s['mechanism']['summary']))
                self.assertEqual(i['hypothesis'], norm(s['hypothesis']['statement']))
                self.assertEqual(i['minimal_test'], norm(s['test']['one_line']))

    def test_answer_format_is_the_preregistered_criterion(self):
        r, out = self.export()
        b = self.blind(out)
        self.assertEqual(sorted(b['answer_format']['per_idea']),
                         ['executable_minimal_test', 'not_already_done', 'not_noted_by_me'])
        self.assertIn('at_least_one_worth_digging', b['answer_format']['per_case'])
        self.assertIn('would_have_found_alone', b['answer_format']['per_case'])
        self.assertIn('data', b['instructions'])
        md = (out / 'blind' / 'case-01.md').read_text(encoding='utf-8')
        self.assertIn('P1', md)
        self.assertIn(b['presentations'][0]['ideas'][0]['title'], md)

    def test_nothing_that_unblinds(self):
        r, out = self.export()
        blob = self.blob(out).lower()
        for bad in ('facet_recombination', 'hypothesis_inversion', 'literature_bridge', 'valid_vp_rebound',
                    'valid_novp_rebound', 'model-run-1', 'frontier', '"arm"', 'vp_b_01', 'tradeoffs', 'seed', 'shuffle',
                    'random'):
            self.assertNotIn(bad, blob, bad)
        self.assertNotIn('KEY', blob)

    def test_key_is_complete(self):
        r, out = self.export()
        key = self.key()
        self.assertEqual(sorted(key['cases']), ['case-01', 'case-02'])
        c = key['cases']['case-01']
        self.assertEqual(sorted(c['order']), ['A', 'B', 'C'])
        self.assertEqual(len(c['ideas']), 15)
        self.assertIn('case-01', json.dumps(key))


class SecretSeedTest(ExportBase):
    """RB32."""

    def test_the_seed_is_random_32_bytes_and_only_in_the_key(self):
        r, out = self.export()
        seed = self.key()['seed_hex']
        self.assertRegex(seed, r'^[0-9a-f]{64}$')
        self.assertNotIn(seed, self.blob(out))
        self.assertNotIn(seed, r.stdout + r.stderr)

    def test_two_exports_have_two_seeds(self):
        self.export(self.tmp / 'o1')
        s1 = self.key()['seed_hex']
        self.keyfile().unlink()
        self.export(self.tmp / 'o2')
        self.assertNotEqual(s1, self.key()['seed_hex'])

    def test_no_public_seed_option(self):
        r, out = self.export(None, '--seed', '20261114')
        self.assertEqual(r.returncode, 2)
        self.assertFalse(out.exists())

    def test_order_is_the_documented_draw(self):
        r, out = self.export()
        key = self.key()
        for case, n in (('case-01', 5), ('case-02', 5)):
            rng = case_rng(key['seed_hex'], case)
            arms = ['A', 'B', 'C']
            rng.shuffle(arms)
            self.assertEqual(key['cases'][case]['order'], arms)
            perms = {}
            for label in ('P1', 'P2', 'P3'):
                idx = list(range(n))
                rng.shuffle(idx)
                perms[label] = idx
            b = self.blind(out, case)
            for pos, label in enumerate(('P1', 'P2', 'P3')):
                arm = arms[pos]
                self.assertEqual(key['cases'][case]['labels'][label], arm)
                ids = [i['idea_id'] for i in b['presentations'][pos]['ideas']]
                self.assertEqual(ids, ['%s-%s-%d' % (case, label, k + 1) for k in range(n)])
                mapped = [key['cases'][case]['ideas'][i] for i in ids]
                self.assertEqual([m['arm'] for m in mapped], [arm] * n)
                self.assertEqual([m['index'] for m in mapped], perms[label])

    def test_the_old_public_draw_does_not_reproduce_the_order(self):
        # knowing the case id and the old published seed must not give the arms back (checked over many seeds)
        mismatches = 0
        for k in range(8):
            self.fresh()
            self.keyfile().parent.mkdir(parents=True, exist_ok=True)
            r, out = self.export()
            old = random.Random('20261114:case-01')
            arms = ['A', 'B', 'C']
            old.shuffle(arms)
            mismatches += int(self.key()['cases']['case-01']['order'] != arms)
        self.assertGreater(mismatches, 2)       # a fixed draw would match in about 1 case out of 6

    def test_from_key_gives_the_same_bytes(self):
        r1, o1 = self.export(self.tmp / 'o1')
        self.assertEqual(r1.returncode, 0)
        r2 = run_tool('export_rebound', '--manifest', self.manifest(), '--out', self.tmp / 'o2', '--from-key', self.keyfile())
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertEqual(self.tree_bytes(o1), self.tree_bytes(self.tmp / 'o2'))

    def test_from_key_refuses_a_changed_manifest(self):
        self.export(self.tmp / 'o1')
        m = read_json(self.manifest())
        m['cases'] = m['cases'][:1]
        write_json(self.manifest(), m)
        r2 = run_tool('export_rebound', '--manifest', self.manifest(), '--out', self.tmp / 'o2', '--from-key', self.keyfile())
        self.assertEqual(r2.returncode, 2)

    def test_the_key_goes_outside_the_export(self):
        out = self.tmp / 'out'
        r = run_tool('export_rebound', '--manifest', self.manifest(), '--out', out, '--key', out / 'KEY.json')
        self.assertEqual(r.returncode, 2)
        self.assertIn('outside', r.stderr)
        self.assertFalse(out.exists())

    def test_a_key_is_required(self):
        r, out = self.export(None, key=False)
        self.assertEqual(r.returncode, 2)

    def test_an_existing_key_is_not_overwritten(self):
        self.export(self.tmp / 'o1')
        r, out = self.export(self.tmp / 'o2')
        self.assertEqual(r.returncode, 2)
        self.assertIn('exists', r.stderr)

    def test_cases_are_independent_of_each_other(self):
        r, out = self.export()
        full = (out / 'blind' / 'case-02.json').read_bytes()
        m = read_json(self.manifest())
        m['cases'] = [m['cases'][1]]
        write_json(self.manifest(), m)
        key0 = self.key()
        key0['manifest_sha256'] = hashlib.sha256(self.manifest().read_bytes()).hexdigest()
        write_json(self.tmp / 'key2.json', key0)
        r2 = run_tool('export_rebound', '--manifest', self.manifest(), '--out', self.tmp / 'alone', '--from-key',
                      self.tmp / 'key2.json')
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertEqual((self.tmp / 'alone' / 'blind' / 'case-02.json').read_bytes(), full)


class UniformFormatTest(ExportBase):
    """RB33."""

    def labelled(self, out, case='case-01'):
        key = self.key()['cases'][case]
        b = self.blind(out, case)
        return {key['labels'][p['label']]: p for p in b['presentations']}

    def test_no_prior_art_in_the_blind_lists(self):
        r, out = self.export()
        for case in ('case-01', 'case-02'):
            for p in self.blind(out, case)['presentations']:
                for i in p['ideas']:
                    self.assertNotIn('prior_art', i)
        md = (out / 'blind' / 'case-01.md').read_text(encoding='utf-8').lower()
        self.assertNotIn('prior art:', md)
        self.assertNotIn('not checked', md)

    def test_prior_art_form_is_the_same_for_every_idea(self):
        r, out = self.export()
        form = read_json(out / 'blind' / 'case-01.prior-art-form.json')
        b = self.blind(out)
        ids = [i['idea_id'] for p in b['presentations'] for i in p['ideas']]
        self.assertEqual(sorted(form['ideas']), sorted(ids))
        self.assertEqual(len({json.dumps(v, sort_keys=True) for v in form['ideas'].values()}), 1)
        one = next(iter(form['ideas'].values()))
        self.assertEqual(sorted(one), ['closest_work', 'queries', 'status'])
        self.assertIsNone(one['status'])
        self.assertIn('same', form['instructions'])

    def test_prior_art_of_a_and_b_goes_to_the_key(self):
        r, out = self.export()
        key = self.key()['cases']['case-01']
        statuses = {}
        for iid, m in key['ideas'].items():
            statuses.setdefault(m['arm'], set()).add(json.dumps((m.get('prior_art') or {}).get('status')))
        self.assertIn('"Exists"', statuses['A'])
        self.assertIn('"Partially"', statuses['A'])
        self.assertEqual(statuses['C'], {'null'})
        self.assertEqual(statuses['B'], {'null'})      # a baseline carries no prior art: the form is filled for the three lists
        for iid, m in key['ideas'].items():
            self.assertIn('references', m)

    def test_references_are_normalised_sorted_and_unique(self):
        mutate(self.fx_export(''), 'c_01.json', lambda d: d['ideas'][0].update(
            references=[{'id': 'DOI:10.1000/X.2'}, {'id': 'https://doi.org/10.1000/a.1'}, {'id': 'doi:10.1000/x.2'}]))
        r, out = self.export()
        self.assertEqual(r.returncode, 0, r.stderr)
        arms = self.labelled(out)
        refs = [i['references'] for i in arms['C']['ideas'] if i['title'].startswith('Model alone idea 1') or True]
        found = [x for x in refs if 'doi:10.1000/x.2' in x][0]
        self.assertEqual(found, ['doi:10.1000/a.1', 'doi:10.1000/x.2'])

    def test_no_status_beside_a_reference(self):
        r, out = self.export()
        for p in self.blind(out)['presentations']:
            for i in p['ideas']:
                for x in i['references']:
                    self.assertIsInstance(x, str)

    def test_text_is_cleaned_the_same_way_for_every_arm(self):
        mutate(self.fx_export(''), 'c_01.json', lambda d: d['ideas'][0].update(
            statement='  **Bold** statement   with `code` and  spaces ', title='A title.'))
        mutate(self.fx_export(''), 'b_01.json', lambda d: d['ideas'][0].update(
            statement='  **Bold** statement   with `code` and  spaces ', title='A title.'))
        r, out = self.export()
        self.assertEqual(r.returncode, 0, r.stderr)
        for p in self.blind(out)['presentations']:
            for i in p['ideas']:
                if i['title'] == 'A title':
                    self.assertEqual(i['statement'], 'Bold statement with code and spaces.')
                self.assertFalse(i['statement'].endswith('..'))
                self.assertNotIn('  ', i['statement'])
                self.assertNotIn('**', i['statement'])
                self.assertTrue(i['statement'].endswith('.'))
        found = [i for p in self.blind(out)['presentations'] for i in p['ideas'] if i['title'] == 'A title']
        self.assertEqual(len(found), 2)        # the same cleaning in arms B and C

    def test_references_of_the_three_arms_have_one_format(self):
        r, out = self.export()
        for case in ('case-01', 'case-02'):
            for p in self.blind(out, case)['presentations']:
                for i in p['ideas']:
                    for x in i['references']:
                        self.assertRegex(x, r'^[a-z]+:\S+$')
                        self.assertEqual(x, x.lower())


class ReferencesTest(ExportBase):
    """RB35."""

    def test_key_gives_a_status_per_reference_and_arm(self):
        r, out = self.export()
        key = self.key()['cases']['case-01']
        by_arm = {}
        for iid, m in key['ideas'].items():
            for ref in m['references']:
                by_arm.setdefault(m['arm'], set()).add(ref['status'])
        self.assertIn('FOUND', by_arm['A'])
        self.assertIn('FOUND', by_arm['B'])
        self.assertEqual(by_arm['C'], {'unverified'})

    def test_arm_a_without_vp_is_unverified(self):
        r, out = self.export()
        key = self.key()['cases']['case-02']
        a = {ref['status'] for m in key['ideas'].values() if m['arm'] == 'A' for ref in m['references']}
        self.assertEqual(a, {'unverified'})

    def test_flat_list_to_check_has_no_arm(self):
        r, out = self.export()
        flat = read_json(out / 'blind' / 'case-01.references-to-check.json')
        self.assertEqual(sorted(flat), ['case_id', 'instructions', 'references'])
        self.assertEqual(flat['references'], sorted(set(flat['references'])))
        shown = {x for p in self.blind(out)['presentations'] for i in p['ideas'] for x in i['references']}
        self.assertEqual(set(flat['references']), shown)

    def test_an_absent_reference_of_arm_b_is_counted_not_refused(self):
        def go(d):
            d['claims'][0]['status'] = 'ABSENT'
        mutate(self.fx_export('vp_b_01'), 'verdicts.json', go)
        r, out = self.export()
        self.assertEqual(r.returncode, 0, r.stderr)
        statuses = {ref['status'] for m in self.key()['cases']['case-01']['ideas'].values() if m['arm'] == 'B'
                    for ref in m['references']}
        self.assertEqual(statuses, {'ABSENT'})

    def test_arm_b_reference_without_run_and_claim(self):
        mutate(self.fx_export(''), 'b_01.json', lambda d: d['ideas'][0].update(references=[{'id': 'doi:10.1000/b.2020'}]))
        r, out = self.export()
        self.assertEqual(r.returncode, 2)
        self.assertIn('run', r.stderr)

    def test_arm_c_reference_with_a_run(self):
        mutate(self.fx_export(''), 'c_01.json', lambda d: d['ideas'][0].update(
            references=[{'id': 'doi:10.1000/b.2020', 'run': 'vp_b_01', 'claim': 'A1'}]))
        r, out = self.export()
        self.assertEqual(r.returncode, 2)

    def test_arm_b_reference_that_is_not_the_claim_source(self):
        mutate(self.fx_export(''), 'b_01.json', lambda d: d['ideas'][0].update(
            references=[{'id': 'doi:10.1000/other.1', 'run': 'vp_b_01', 'claim': 'A1'}]))
        r, out = self.export()
        self.assertEqual(r.returncode, 0, r.stderr)
        sts = [ref['status'] for m in self.key()['cases']['case-01']['ideas'].values() if m['arm'] == 'B'
               for ref in m['references'] if ref['id'] == 'doi:10.1000/other.1']
        self.assertEqual(sts, ['MISMATCH'])


class BaselineAttestationTest(ExportBase):
    """RB34."""

    def refused(self, why=None):
        r, out = self.export()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse(out.exists())
        if why:
            self.assertIn(why, r.stderr)

    def test_parent_idea_of_b(self):
        mutate(self.fx_export(''), 'b_01.json', lambda d: d.update(parent_idea='Another idea about something else entirely.'))
        self.refused('parent_idea')

    def test_parent_idea_of_c(self):
        mutate(self.fx_export(''), 'c_01.json', lambda d: d.update(parent_idea='Another idea about something else entirely.'))
        self.refused('parent_idea')

    def test_parent_idea_spaces_do_not_matter(self):
        mutate(self.fx_export(''), 'c_01.json', lambda d: d.update(parent_idea='  ' + d['parent_idea'].replace(' ', '  ') + ' '))
        r, out = self.export()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_date_of_the_idea(self):
        mutate(self.fx_export(''), 'c_01.json', lambda d: d.update(T='2025-01-01'))
        self.refused('T')

    def test_b_needs_vp_runs_naming_its_vp_run(self):
        mutate(self.fx_export(''), 'b_01.json', lambda d: d.pop('vp_runs'))
        self.refused('vp_runs')

    def test_b_vp_run_must_be_in_vp_runs(self):
        mutate(self.fx_export(''), 'b_01.json', lambda d: d.update(vp_run='vp_other'))
        self.refused('vp_run')

    def test_vp_run_directory_must_exist(self):
        mutate(self.fx_export(''), 'b_01.json', lambda d: d.update(vp_runs={'vp_b_01': 'nowhere'}))
        self.refused('vp_b_01')

    def test_journal_is_required(self):
        (self.fx_export('vp_b_01') / 'state' / 'journal.jsonl').unlink()
        self.refused('journal')

    def test_journal_needs_a_search_call(self):
        p = self.fx_export('vp_b_01') / 'state' / 'journal.jsonl'
        rows = [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines()]
        for r in rows:
            r['call'] = 'fetch'
        p.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')
        self.refused('search')

    def test_journal_must_not_run_after_t(self):
        p = self.fx_export('vp_b_01') / 'state' / 'journal.jsonl'
        rows = [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines()]
        for r in rows:
            r['T'] = '2027-01-01'
        p.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')
        self.refused('T')

    def test_generated_utc_is_required_in_the_file(self):
        mutate(self.fx_export(''), 'b_01.json', lambda d: d.pop('generated_utc'))
        self.refused()


class ResearcherNotesTest(ExportBase):
    """RB37."""

    def make_notes(self, case='case-01', utc='2026-11-14T12:00:00Z', name='mine.json', text='My own ideas, written first.\n'):
        t = self.tmp / (name + '.txt')
        t.write_text(text, encoding='utf-8')
        return run_tool('export_rebound', 'notes', '--case-id', case, '--text-file', t, '--out', self.tmp / name, '--utc', utc)

    def test_notes_command_writes_hash_and_time(self):
        r = self.make_notes()
        self.assertEqual(r.returncode, 0, r.stderr)
        d = read_json(self.tmp / 'mine.json')
        self.assertEqual(d['case_id'], 'case-01')
        self.assertEqual(d['written_utc'], '2026-11-14T12:00:00Z')
        self.assertEqual(d['sha256'], hashlib.sha256('My own ideas, written first.\n'.encode('utf-8')).hexdigest())
        self.assertIn('My own ideas', d['text'])

    def test_registered_notes_are_never_overwritten(self):
        self.assertEqual(self.make_notes().returncode, 0)
        r = self.make_notes(text='Another text, written later.\n')
        self.assertEqual(r.returncode, 2)
        self.assertIn('never overwritten', r.stderr)
        self.assertIn('My own ideas', read_json(self.tmp / 'mine.json')['text'])

    def test_notes_command_needs_text_and_valid_time(self):
        self.assertEqual(run_tool('export_rebound', 'notes', '--case-id', 'x', '--text-file', self.tmp / 'no.txt',
                                  '--out', self.tmp / 'o.json').returncode, 2)
        self.assertEqual(self.make_notes(utc='yesterday').returncode, 2)

    def test_key_keeps_hash_and_time_but_the_export_not_the_text(self):
        r, out = self.export()
        n = self.key()['cases']['case-01']['researcher_notes']
        notes = read_json(self.fx_export('notes_01.json'))
        self.assertEqual(n, {'sha256': notes['sha256'], 'written_utc': notes['written_utc']})
        self.assertNotIn(notes['text'][:30], self.blob(out))

    def test_a_cases_needs_its_notes(self):
        m = read_json(self.manifest())
        m['cases'][0].pop('researcher_notes')
        write_json(self.manifest(), m)
        r, out = self.export()
        self.assertEqual(r.returncode, 2)
        self.assertIn('researcher_notes', r.stderr)

    def test_a_wrong_hash(self):
        mutate(self.fx_export(''), 'notes_01.json', lambda d: d.update(text=d['text'] + 'added afterwards'))
        r, out = self.export()
        self.assertEqual(r.returncode, 2)
        self.assertIn('sha256', r.stderr)

    def test_notes_must_precede_every_arm(self):
        for when in ('2026-11-14T13:30:00Z', '2026-11-14T13:31:00Z', '2026-11-14T13:32:00Z', '2026-11-14T18:00:00Z'):
            with self.subTest(written=when):
                self.fresh()
                mutate(self.fx_export(''), 'notes_01.json', lambda d: d.update(written_utc=when))
                r, out = self.export()
                self.assertEqual(r.returncode, 2, r.stdout)
                self.assertIn('before', r.stderr)

    def test_notes_of_another_case(self):
        mutate(self.fx_export(''), 'notes_01.json', lambda d: d.update(case_id='case-02'))
        r, out = self.export()
        self.assertEqual(r.returncode, 2)

    def test_the_limit_is_written(self):
        r = run_tool('export_rebound', '--help')
        self.assertIn('hash', r.stdout.lower())
        self.assertIn('publish', r.stdout.lower())


class RefusalTest(ExportBase):
    def test_different_number_of_ideas(self):
        mutate(self.fx / 'export_rebound', 'b_01.json', lambda d: d['ideas'].pop())
        r, out = self.export()
        self.assertEqual(r.returncode, 2)
        self.assertIn('same number', r.stderr)
        self.assertFalse(out.exists())

    def test_leak_of_a_label(self):
        for field, text in (('title', 'A Frontier operator idea'), ('statement', 'Chosen by the facet_recombination step.'),
                            ('statement', 'Made by facet recombination of the parent idea.')):
            with self.subTest(field=field, text=text):
                self.fresh()
                self.idea(VP, 'N1', lambda i: i.update({field: text}))
                r, out = self.export()
                self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
                self.assertFalse(out.exists())

    def test_ordinary_words_rebound_and_operator_do_not_refuse(self):
        # round 2 (RB33): only real traces of the source refuse; a "rebound effect" is ordinary science
        self.idea(VP, 'N1', lambda i: i.update(statement='A rebound effect of the survey operator on citation counts is tested.'))
        r, out = self.export()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_leak_of_the_producer(self):
        mutate(self.fx / 'export_rebound', 'c_01.json', lambda d: d['ideas'][0].update(title='From model-run-1-alone here'))
        r, out = self.export()
        self.assertEqual(r.returncode, 3)

    def test_leak_of_the_vp_run_name(self):
        mutate(self.fx / 'export_rebound', 'c_01.json', lambda d: d['ideas'][0].update(title='Seen in vp_b_01 of the pilot'))
        r, out = self.export()
        self.assertEqual(r.returncode, 3)

    def test_arm_a_must_pass_check(self):
        self.idea(VP, 'N1', lambda i: i.update(operator='magic'))
        r, out = self.export()
        self.assertEqual(r.returncode, 2)
        self.assertIn('check', r.stderr.lower())

    def test_arm_b_names_its_vp_run(self):
        mutate(self.fx / 'export_rebound', 'b_01.json', lambda d: d.pop('vp_run'))
        r, out = self.export()
        self.assertEqual(r.returncode, 2)

    def test_wrong_arm_in_a_baseline(self):
        mutate(self.fx / 'export_rebound', 'c_01.json', lambda d: d.update(arm='B', vp_run='x'))
        r, out = self.export()
        self.assertEqual(r.returncode, 2)

    def test_existing_foreign_output_directory(self):
        out = self.tmp / 'out'
        out.mkdir()
        (out / 'precious.txt').write_text('x', encoding='utf-8')
        r, _ = self.export(out)
        self.assertEqual(r.returncode, 2)
        self.assertTrue((out / 'precious.txt').exists())

    def test_own_output_directory_is_replaced(self):
        r, out = self.export()
        self.assertEqual(r.returncode, 0)
        r = run_tool('export_rebound', '--manifest', self.manifest(), '--out', out, '--from-key', self.keyfile())
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_usage(self):
        self.assertEqual(run_tool('export_rebound').returncode, 2)
        self.assertEqual(run_tool('export_rebound', '--manifest', self.tmp / 'none.json', '--out', self.tmp / 'o',
                                  '--key', self.tmp / 'k.json').returncode, 2)

    def test_manifest_needs_three_arms(self):
        m = read_json(self.manifest())
        m['cases'][0].pop('C')
        write_json(self.manifest(), m)
        r, out = self.export()
        self.assertEqual(r.returncode, 2)

    def test_duplicate_case_ids(self):
        m = read_json(self.manifest())
        m['cases'][1]['case_id'] = 'case-01'
        write_json(self.manifest(), m)
        r, out = self.export()
        self.assertEqual(r.returncode, 2)


class StatsTest(ExportBase):
    """RB36: the written stopping rule, computed."""

    def setUp(self):
        super().setUp()
        r, self.out = self.export()
        self.assertEqual(r.returncode, 0, r.stderr)

    def answers(self, retained, minutes=10):
        """retained = {arm: number of ideas of each list answered true, true, true}; the others get one false."""
        key = self.key()
        ans = {}
        for case, c in key['cases'].items():
            per = {}
            count = {'A': 0, 'B': 0, 'C': 0}
            for iid, m in sorted(c['ideas'].items()):
                ok = count[m['arm']] < retained[m['arm']]
                count[m['arm']] += 1
                per[iid] = {'not_noted_by_me': True, 'not_already_done': ok, 'executable_minimal_test': True}
            ans[case] = {'ideas': per, 'at_least_one_worth_digging': True, 'would_have_found_alone': [],
                         'prior_art_missed': [], 'judge_minutes': minutes}
        return ans

    def stats(self, ans, *extra):
        write_json(self.tmp / 'answers.json', ans)
        r = run_tool('export_rebound', 'stats', '--key', self.keyfile(), '--answers', self.tmp / 'answers.json', *extra)
        return r, (json.loads(r.stdout) if r.returncode in (0, 1) and r.stdout.strip().startswith('{') else None)

    def test_shares_and_difference(self):
        r, s = self.stats(self.answers({'A': 4, 'B': 2, 'C': 1}))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(s['arms']['A']['ideas'], 10)
        self.assertEqual(s['arms']['A']['retained'], 8)
        self.assertEqual(s['arms']['B']['retained'], 4)
        self.assertAlmostEqual(s['arms']['A']['share'], 0.8)
        self.assertAlmostEqual(s['difference_A_minus_B'], 0.4)
        self.assertTrue(s['rule_difference']['met'])
        self.assertEqual(s['rule_difference']['threshold'], 0.2)

    def test_a_beats_b_by_exactly_one_in_five(self):
        r, s = self.stats(self.answers({'A': 3, 'B': 2, 'C': 0}))
        self.assertAlmostEqual(s['difference_A_minus_B'], 0.2)
        self.assertTrue(s['rule_difference']['met'])
        self.assertFalse(s['stop'])

    def test_stop_when_a_does_not_beat_b_enough(self):
        r, s = self.stats(self.answers({'A': 2, 'B': 2, 'C': 0}))
        self.assertFalse(s['rule_difference']['met'])
        self.assertTrue(s['stop'])
        self.assertIn('difference', ' '.join(s['reasons']))

    def test_stop_when_arm_a_references_are_false(self):
        key = self.key()
        a_refs = {ref['id'] for c in key['cases'].values() for m in c['ideas'].values() if m['arm'] == 'A'
                  for ref in m['references']}
        audit = {rid: 'ABSENT' for rid in a_refs}
        write_json(self.tmp / 'audit.json', audit)
        r, s = self.stats(self.answers({'A': 4, 'B': 1, 'C': 0}), '--reference-audit', self.tmp / 'audit.json')
        self.assertGreater(s['rule_false_references']['arm_A_false_share'], 0.1)
        self.assertTrue(s['rule_false_references']['exceeded'])
        self.assertTrue(s['stop'])

    def test_the_audit_overrides_the_key(self):
        key = self.key()
        some = next(ref['id'] for c in key['cases'].values() for m in c['ideas'].values() if m['arm'] == 'C'
                    for ref in m['references'])
        write_json(self.tmp / 'audit.json', {some: 'FOUND'})
        r, s = self.stats(self.answers({'A': 4, 'B': 2, 'C': 1}), '--reference-audit', self.tmp / 'audit.json')
        self.assertGreater(s['arms']['C']['references']['found'], 0)

    def test_references_are_reported_per_arm_with_unverified_apart(self):
        r, s = self.stats(self.answers({'A': 4, 'B': 2, 'C': 1}))
        for arm in 'ABC':
            ref = s['arms'][arm]['references']
            self.assertEqual(sorted(ref), ['false', 'false_share', 'found', 'total', 'unverified', 'unverified_share'])
            self.assertEqual(ref['total'], ref['found'] + ref['false'] + ref['unverified'])
        self.assertEqual(s['arms']['C']['references']['found'], 0)
        self.assertGreater(s['arms']['C']['references']['unverified'], 0)

    def test_duplicates_missed_prior_art_and_minutes(self):
        ans = self.answers({'A': 4, 'B': 2, 'C': 1}, minutes=7)
        c = self.key()['cases']['case-01']
        first_a = sorted(i for i, m in c['ideas'].items() if m['arm'] == 'A')[0]
        ans['case-01']['prior_art_missed'] = [first_a]
        r, s = self.stats(ans)
        self.assertEqual(s['arms']['A']['prior_art_missed'], 1)
        self.assertEqual(s['arms']['B']['prior_art_missed'], 0)
        self.assertEqual(s['judge_minutes'], 14)
        for arm in 'ABC':
            self.assertIn('duplicate_groups', s['arms'][arm])

    def test_limits_are_in_the_output(self):
        r, s = self.stats(self.answers({'A': 4, 'B': 2, 'C': 1}))
        text = ' '.join(s['limits']).lower()
        self.assertIn('exploratory', text)
        self.assertIn('single judge', text)
        self.assertIn('no generalisation', text)

    def test_human_output(self):
        write_json(self.tmp / 'answers.json', self.answers({'A': 4, 'B': 2, 'C': 1}))
        r = run_tool('export_rebound', 'stats', '--key', self.keyfile(), '--answers', self.tmp / 'answers.json', '--text')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('arm A', r.stdout)
        self.assertIn('stop', r.stdout.lower())

    def test_exit_code_one_when_the_rule_says_stop(self):
        r, s = self.stats(self.answers({'A': 2, 'B': 2, 'C': 0}), '--exit-code')
        self.assertEqual(r.returncode, 1)

    def test_a_missing_answer(self):
        ans = self.answers({'A': 4, 'B': 2, 'C': 1})
        ans['case-01']['ideas'].pop(next(iter(ans['case-01']['ideas'])))
        r, _ = self.stats(ans)
        self.assertEqual(r.returncode, 2)
        self.assertIn('answer', r.stderr)

    def test_an_unknown_idea(self):
        ans = self.answers({'A': 4, 'B': 2, 'C': 1})
        ans['case-01']['ideas']['case-01-P9-9'] = {'not_noted_by_me': True, 'not_already_done': True, 'executable_minimal_test': True}
        r, _ = self.stats(ans)
        self.assertEqual(r.returncode, 2)

    def test_a_non_boolean_answer(self):
        ans = self.answers({'A': 4, 'B': 2, 'C': 1})
        first = next(iter(ans['case-01']['ideas']))
        ans['case-01']['ideas'][first]['not_already_done'] = 'yes'
        r, _ = self.stats(ans)
        self.assertEqual(r.returncode, 2)

    def test_unreadable_inputs(self):
        r = run_tool('export_rebound', 'stats', '--key', self.tmp / 'none.json', '--answers', self.tmp / 'none2.json')
        self.assertEqual(r.returncode, 2)
