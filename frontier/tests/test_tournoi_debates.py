# SPDX-License-Identifier: Apache-2.0
"""Oracle first: reduced reference round-2/privacy tests and reviewer regressions.

Only rebound.json is a candidate source. Source hypotheses remain public context.
The card compares the original statements; repairs are explicitly historical.
"""
import contextlib
import copy
import io
import json
import multiprocessing
from pathlib import Path
from unittest import mock

from .helpers import (FRONTIER, TempCase, copy_skill, load_tool, mutate, read_json,
                      run_tool, set_config, write_json)
from .test_tournoi import debate, scope, settings
from .test_v2_rebound import plan_of
from .v2_common import V2


def locked_recorder(skill, work, debate_path, attempting, read_event, result):
    """Signal the actual flock call and first journal read in a fresh process."""
    tool = load_tool('tournoi')
    real_flock, real_read = tool.fcntl.flock, tool.common.read_json

    def flock(fd, operation):
        attempting.set()
        return real_flock(fd, operation)

    def read(path):
        if Path(path).name == 'tournoi_rebound.json':
            read_event.set()
        return real_read(path)

    with mock.patch.object(tool.common, 'FRONTIER', Path(skill)), \
            mock.patch.object(tool.fcntl, 'flock', flock), \
            mock.patch.object(tool.common, 'read_json', read), \
            contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        result.put(tool.main(['record', work, '--debate', debate_path]))


class DebatesOracle(TempCase):
    def setUp(self):
        super().setUp()
        self.skill = copy_skill(self.tmp, 'skill')
        set_config(self.skill, lambda c: c.update(
            tournoi=settings(max_debates=4),
            critic=dict(c['critic'], host_family='author-family', families=[])))
        self.w = self.work('valid_novp_rebound')
        self.journal = self.w / 'tournoi_rebound.json'
        self.scope_path = self.w / 'scope.json'
        write_json(self.scope_path, scope())

    def cli(self, command, *args):
        return run_tool('tournoi', command, self.w.relative_to(self.tmp), *args,
                        cwd=self.tmp, tools_dir=self.skill / 'tools')

    def init(self, ids=('N1', 'N2')):
        return self.cli('init', '--source', 'rebound.json', '--scope',
                        self.scope_path.relative_to(self.tmp), '--ids', *ids)

    def start(self, ids=('N1', 'N2')):
        p = self.init(ids)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def packet(self):
        p = self.cli('pack')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads(p.stdout)

    def save_debate(self, packet=None, **changes):
        packet = packet or self.packet()
        d = debate(*packet['pair'])
        d['input_sha256'] = packet['input_sha256']
        d.update(changes)
        path = self.w / 'debate.json'
        write_json(path, d)
        return path

    def record(self, packet=None, **changes):
        path = self.save_debate(packet, **changes)
        return self.cli('record', '--debate', path.relative_to(self.tmp))

    def edit_statement(self, text):
        data = read_json(self.w / 'rebound.json')
        old = data['ideas'][0]['statement']
        data['ideas'][0]['statement'] = text
        write_json(self.w / 'rebound.json', data)
        return old

    def repair_file(self, old_text, new_text, **changes):
        d = dict(id='N1', before=old_text, after=new_text,
                 reason='Clarify the control in response to the recorded objection.',
                 match_numbers=[1])
        d.update(changes)
        path = self.w / 'repair.json'
        write_json(path, d)
        return path

    def repair(self, path):
        return self.cli('repair', '--repair', path.relative_to(self.tmp))

    def test_round_trip_preserves_sources_and_cannot_overwrite_init(self):
        names = ('rebound.json', 'hypotheses.json', 'tests.json', 'decision_log.jsonl')
        before = {n: (self.w / n).read_bytes() for n in names}
        self.start()
        original = self.journal.read_bytes()
        self.assertNotEqual(self.init().returncode, 0)
        self.assertEqual(self.journal.read_bytes(), original)
        self.assertEqual(self.record().returncode, 0)
        out = json.loads(self.cli('show').stdout)
        self.assertEqual(out['ratings'], {'N1': 1016, 'N2': 984})
        self.assertEqual(out['match_count'], 1)
        self.assertEqual(out['top_ids'], ['N1'])
        self.assertEqual({n: (self.w / n).read_bytes() for n in names}, before)

    def test_removed_commands_and_other_sources_are_unavailable(self):
        for command in ('evolve', 'restart', 'parents'):
            self.assertNotEqual(self.cli(command).returncode, 0)
        for source in ('hypotheses.json', 'rebound_after.json'):
            self.assertNotEqual(self.cli('init', '--source', source, '--scope',
                                         self.scope_path.relative_to(self.tmp), '--ids', 'H1', 'H2').returncode, 0)
        self.assertFalse(self.journal.exists())

    def test_duplicate_candidate_id_refused_without_writing_journal(self):
        data = read_json(self.w / 'rebound.json')
        data['ideas'].append(copy.deepcopy(data['ideas'][0]))
        write_json(self.w / 'rebound.json', data)
        self.assertNotEqual(self.init().returncode, 0)
        self.assertFalse(self.journal.exists())

    def test_cross_category_duplicate_hypothesis_id_refused(self):
        data = read_json(self.w / 'hypotheses.json')
        data['rivals'][0]['id'] = 'H1'
        data['rivals'][0]['statement'] = 'A conflicting contextual statement.'
        write_json(self.w / 'hypotheses.json', data)
        p = self.init()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('duplicate', p.stderr)
        self.assertFalse(self.journal.exists())

    def test_duplicate_test_ids_cannot_smuggle_an_unlinked_test_into_packet(self):
        self.start()
        state = read_json(self.journal)
        data = read_json(self.w / 'tests.json')
        linked = copy.deepcopy(data['tests'][0])
        unlinked = copy.deepcopy(linked)
        unlinked['competing_hypotheses'] = ['V1']
        # The formerly accepted order put the valid duplicate last in the
        # lookup, then projected both records into the public packet.
        tool = load_tool('tournoi')
        for records in ([unlinked, linked], [linked, unlinked]):
            data['tests'] = records
            write_json(self.w / 'tests.json', data)
            with self.subTest(order=[t['competing_hypotheses'] for t in records], surface='links'):
                with self.assertRaisesRegex(ValueError, 'duplicate test identifier'):
                    tool.link_issues(self.w, state['scope'], 'scope')
            with self.subTest(surface='packet'):
                with self.assertRaisesRegex(ValueError, 'duplicate test identifier'):
                    tool.public_packet(self.w, state)
            with self.subTest(surface='CLI'):
                p = self.cli('pack')
                self.assertNotEqual(p.returncode, 0)
                self.assertEqual(p.stdout, '')
                self.assertIn('duplicate test identifier', p.stderr)
        self.journal.unlink()
        p = self.init()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('duplicate test identifier', p.stderr)
        self.assertFalse(self.journal.exists())

    def test_missing_snapshots_after_debate_and_statement_change_are_refused(self):
        mutate(self.w, 'critique.json', lambda d: d.update(
            author_family='author-family', critic_family='author-family'))
        self.start()
        self.assertEqual(self.record().returncode, 0)
        state = read_json(self.journal)
        after = 'Clarify the original statement after the first debate.'
        before = self.edit_statement(after)
        repair_path = self.repair_file(before, after)
        tool = load_tool('tournoi')
        for missing in (('source_digests',), ('original_statements',),
                        ('source_digests', 'original_statements')):
            incomplete = copy.deepcopy(state)
            for key in missing:
                del incomplete[key]
            write_json(self.journal, incomplete)
            original = self.journal.read_bytes()
            # If the old implementation emits a new packet, submit that exact
            # hash so stale-packet protection cannot mask this regression.
            packet_result = self.cli('pack')
            packet = json.loads(packet_result.stdout) if packet_result.returncode == 0 else {
                'pair': ['N2', 'N1'], 'input_sha256': 'a' * 64}
            path = self.save_debate(packet)
            for command, args in (('show', ()), ('next', ()), ('pack', ()),
                                  ('record', ('--debate', path.relative_to(self.tmp))),
                                  ('repair', ('--repair', repair_path.relative_to(self.tmp)))):
                with self.subTest(missing=missing, command=command):
                    p = self.cli(command, *args)
                    self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
                    self.assertEqual(p.stdout, '')
                    for key in missing:
                        self.assertIn(key, p.stderr)
                    self.assertEqual(self.journal.read_bytes(), original)
                # Keep each surface independent if a broken writer succeeded.
                write_json(self.journal, incomplete)
            with self.subTest(missing=missing, surface='scope'):
                with self.assertRaisesRegex(ValueError, missing[0]):
                    tool.scope_issues(self.w, incomplete)
            with self.subTest(missing=missing, surface='card and report'):
                p = run_tool('card', self.w, tools_dir=self.skill / 'tools')
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                card = (self.w / 'IDEA-CARD.md').read_text()
                report = (self.w / 'IDEA-REPORT.md').read_text()
                self.assertIn('top ideas: unavailable', card)
                for key in missing:
                    self.assertIn(key, report)
                self.assertNotIn('Replayed standings and counts:', report)
                self.assertNotIn('1016', report)
                self.assertNotIn('984', report)
                self.assertEqual(self.journal.read_bytes(), original)

    def test_record_refuses_missing_attribution_or_comparison_without_write(self):
        self.start()
        packet = self.packet()
        original = self.journal.read_bytes()
        for key in ('route', 'judge_family', 'comparison'):
            path = self.save_debate(packet)
            d = read_json(path)
            del d[key]
            write_json(path, d)
            with self.subTest(missing=key):
                p = self.cli('record', '--debate', path.relative_to(self.tmp))
                self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertIn(key, p.stderr)
                self.assertEqual(self.journal.read_bytes(), original)
            self.journal.write_bytes(original)

    def test_invalid_scope_or_missing_candidate_never_publishes(self):
        for invalid in ('kind', 'hypothesis', 'test', 'test_link', 'candidate', 'blank'):
            with self.subTest(invalid=invalid):
                sc = scope()
                ids = ('N1', 'N2')
                if invalid == 'kind':
                    sc['candidate_kind'] = 'hypotheses'
                elif invalid == 'hypothesis':
                    sc['hypothesis_ids'] = ['missing']
                elif invalid == 'test':
                    sc['test_ids'] = ['missing']
                elif invalid == 'test_link':
                    sc['hypothesis_ids'] = ['V1']
                elif invalid == 'candidate':
                    ids = ('N1', 'missing')
                else:
                    self.edit_statement(' ')
                write_json(self.scope_path, sc)
                self.assertNotEqual(self.init(ids).returncode, 0)
                self.assertFalse(self.journal.exists())

    def test_public_packet_has_whitelisted_context_and_no_private_metadata(self):
        data = read_json(self.w / 'rebound.json')
        data['ideas'][0]['internal_history'] = {'file': 'private-notes/source', 'excerpt': 'Hidden lesson.'}
        write_json(self.w / 'rebound.json', data)
        self.start()
        packet = self.packet()
        body = json.dumps(packet)
        for forbidden in ('internal_history', 'private-notes', 'ratings', 'source_digests'):
            self.assertNotIn(forbidden, body)
        for key in ('predictions', 'decision_rule', 'decisive_intervention'):
            self.assertIn(key, packet['tests'][0])
        self.assertEqual(packet['pair'], ['N1', 'N2'])
        tool = load_tool('tournoi')
        claimed = packet.pop('input_sha256')
        self.assertEqual(claimed, tool.source_digest(packet))

    def test_free_draft_four_word_overlap_is_nonblocking_and_recorded(self):
        phrase = 'violet astrolabe control persists'
        (self.w / 'free_draft.md').write_text('Draft: ' + phrase + ' under blinding.')
        self.edit_statement('Investigate whether ' + phrase + ' after randomisation.')
        self.start()
        packet = self.packet()
        self.assertIn('[TOURNOI]', ' '.join(packet['marks']))
        self.assertIn('free draft', ' '.join(packet['marks']))
        p = self.record(packet)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(read_json(self.journal)['matches'][0]['packet_marks'])

    def test_archives_context_and_private_paths_precede_draft_exception(self):
        phrase = 'confidential cobalt telescope failure'
        project = self.tmp / 'private-project'
        project.mkdir()
        intake = read_json(self.w / 'intake.json')
        intake['project_dirs'] = [project.name]
        write_json(self.w / 'intake.json', intake)
        for kind in ('project', 'history', 'context', 'project_path', 'history_path'):
            with self.subTest(kind=kind):
                (project / 'trial.md').write_text(phrase if kind == 'project' else '')
                write_json(self.w / 'history.json', {'entries': [{
                    'excerpt': phrase if kind == 'history' else '',
                    'file': 'private-notes/failed-trial.md' if kind == 'history_path' else ''}]})
                write_json(self.w / 'context_candidates.json', {'candidates': [{
                    'summary': phrase if kind == 'context' else ''}]})
                candidate = (project.name if kind == 'project_path' else
                             'private-notes/failed-trial.md' if kind == 'history_path' else
                             'Evidence of ' + phrase + ' remains tentative.')
                (self.w / 'free_draft.md').write_text(candidate)
                self.edit_statement(candidate)
                self.journal.unlink(missing_ok=True)
                self.start()
                before = self.journal.read_bytes()
                p = self.cli('pack')
                self.assertNotEqual(p.returncode, 0)
                self.assertIn('packet withheld', p.stderr)
                self.assertNotIn(candidate, p.stdout + p.stderr)
                path = self.w / 'debate.json'
                write_json(path, debate('N1', 'N2'))
                self.assertNotEqual(self.cli('record', '--debate', path.relative_to(self.tmp)).returncode, 0)
                self.assertEqual(self.journal.read_bytes(), before)

    def test_record_requires_original_packet_hash_and_never_overwrites_it(self):
        self.start()
        packet = self.packet()
        path = self.save_debate(packet)
        before = self.journal.read_bytes()
        for hash_value in (None, 'b' * 64):
            data = read_json(path)
            if hash_value is None:
                data.pop('input_sha256', None)
            else:
                data['input_sha256'] = hash_value
            write_json(path, data)
            self.assertNotEqual(self.cli('record', '--debate', path.relative_to(self.tmp)).returncode, 0)
            self.assertEqual(self.journal.read_bytes(), before)
        self.assertEqual(self.record(packet).returncode, 0)
        self.assertEqual(read_json(self.journal)['matches'][0]['input_sha256'], packet['input_sha256'])

    def test_stale_packet_after_context_change_is_refused(self):
        self.start()
        packet = self.packet()
        data = read_json(self.w / 'tests.json')
        data['tests'][0]['title'] += ' With a new control.'
        write_json(self.w / 'tests.json', data)
        before = self.journal.read_bytes()
        p = self.record(packet)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('packet', p.stderr)
        self.assertEqual(self.journal.read_bytes(), before)

    def test_stale_packet_after_same_pair_recurs_is_refused(self):
        self.start()
        packet = self.packet()
        self.assertEqual(self.record(packet).returncode, 0)
        self.assertEqual(self.record().returncode, 0)
        self.assertEqual(self.packet()['pair'], packet['pair'])
        before = self.journal.read_bytes()
        self.assertNotEqual(self.record(packet).returncode, 0)
        self.assertEqual(self.journal.read_bytes(), before)

    def test_changed_candidate_is_marked_and_no_further_comparison_runs(self):
        self.start()
        packet = self.packet()
        self.edit_statement('A repaired public statement with a blinded control.')
        self.assertIsNone(json.loads(self.cli('next').stdout)['pair'])
        self.assertNotEqual(self.cli('pack').returncode, 0)
        self.assertNotEqual(self.record(packet).returncode, 0)
        self.assertIn('candidate changed', self.cli('show').stdout)

    def test_unrecorded_statement_change_withholds_results_on_every_surface(self):
        mutate(self.w, 'critique.json', lambda d: d.update(
            author_family='author-family', critic_family='author-family'))
        self.start()
        self.assertEqual(self.record().returncode, 0)
        original = self.journal.read_bytes()
        self.edit_statement('Clarify the original statement with a blinded control.')
        tool = load_tool('tournoi')
        p = self.cli('show')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        shown = json.loads(p.stdout)
        state, marks = tool.inspect(self.w)
        rendered = {
            'inspect': '\n'.join(marks),
            'show': p.stdout,
            'summary': tool.summary(self.w),
            'report_lines': '\n'.join(tool.report_lines(self.w)),
        }
        p = run_tool('card', self.w, tools_dir=self.skill / 'tools')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        card = (self.w / 'IDEA-CARD.md').read_text()
        rendered['card'] = '\n'.join(line for line in card.splitlines() if '[TOURNOI]' in line)
        rendered['report'] = (self.w / 'IDEA-REPORT.md').read_text().split(
            '## Rebound ideas tournament', 1)[1]
        with self.subTest(surface='inspect state'):
            self.assertIsNone(state)
        with self.subTest(surface='show scores and standings'):
            for key in ('ratings', 'order', 'top_ids', 'rating_spread'):
                self.assertIsNone(shown.get(key), key)
        for surface, body in rendered.items():
            with self.subTest(surface=surface):
                for phrase in ('unavailable', 'candidate changed without a recorded repair', 'use repair'):
                    self.assertIn(phrase, body)
                for phrase in ('1016', '984', 'no informative preference',
                               'Replayed standings and counts:',
                               'Complete judgment and statement-repair journal:', 'input_sha256'):
                    self.assertNotIn(phrase, body)
                self.assertEqual(self.journal.read_bytes(), original)

    def test_statement_repair_is_audited_without_reset_or_new_candidate(self):
        self.start()
        self.assertEqual(self.record().returncode, 0)
        before_state = read_json(self.journal)
        after = 'Use a blinded positive control to distinguish the proposed mechanism.'
        before = self.edit_statement(after)
        path = self.repair_file(before, after)
        p = self.repair(path)
        self.assertEqual(p.returncode, 0, p.stderr)
        state = read_json(self.journal)
        self.assertEqual(state['matches'], before_state['matches'])
        self.assertEqual(state['candidates'], before_state['candidates'])
        self.assertEqual(state['repairs'][0]['before'], before)
        self.assertEqual(state['repairs'][0]['after'], after)
        self.assertEqual(state['repairs'][0]['match_numbers'], [1])
        self.assertEqual(json.loads(p.stdout)['ratings'], {'N1': 1016, 'N2': 984})
        self.assertIsNone(json.loads(self.cli('next').stdout)['pair'])
        self.assertNotEqual(self.cli('pack').returncode, 0)
        self.assertIn('original statements', self.cli('show').stdout)
        self.assertIn(after, '\n'.join(load_tool('tournoi').report_lines(self.w)))

    def test_repair_requires_actual_before_after_and_relevant_recorded_debate(self):
        self.start()
        self.assertEqual(self.record().returncode, 0)
        after = 'Use a blinded positive control to distinguish the proposed mechanism.'
        before = self.edit_statement(after)
        original = self.journal.read_bytes()
        for changes in ({'before': 'Invented original'}, {'after': 'Invented repair'},
                        {'match_numbers': [99]}, {'match_numbers': []}, {'id': 'N3'},
                        {'reason': ''}):
            with self.subTest(changes=changes):
                p = self.repair_file(before, after, **changes)
                self.assertNotEqual(self.repair(p).returncode, 0)
                self.assertEqual(self.journal.read_bytes(), original)

    def test_all_journal_writers_hold_lock_before_read_and_through_write(self):
        tool = load_tool('tournoi')
        depth = [0]
        real_read, real_write = tool.common.read_json, tool.common.write_json

        @contextlib.contextmanager
        def lock(work):
            self.assertEqual(Path(work), self.w)
            depth[0] += 1
            try:
                yield
            finally:
                depth[0] -= 1

        def read(path):
            if Path(path) == self.journal:
                self.assertEqual(depth[0], 1, 'journal read before lock')
            return real_read(path)

        def write(path, data):
            self.assertEqual(depth[0], 1, 'journal write outside lock')
            return real_write(path, data)

        with mock.patch.object(tool.common, 'FRONTIER', self.skill), \
                mock.patch.object(tool, 'journal_lock', lock), \
                mock.patch.object(tool.common, 'read_json', read), \
                mock.patch.object(tool.common, 'write_json', write), \
                contextlib.redirect_stdout(io.StringIO()):
            argv = ['init', str(self.w), '--scope', str(self.scope_path), '--ids', 'N1', 'N2']
            self.assertEqual(tool.main(argv), 0)
            path = self.save_debate()
            self.assertEqual(tool.main(['record', str(self.w), '--debate', str(path)]), 0)
            after = 'State explicitly that a blinded control is needed.'
            before = self.edit_statement(after)
            path = self.repair_file(before, after)
            self.assertEqual(tool.main(['repair', str(self.w), '--repair', str(path)]), 0)

    def test_init_rechecks_sources_before_commit(self):
        tool = load_tool('tournoi')
        original_validate = tool.validate_state

        def validate(state):
            result = original_validate(state)
            self.edit_statement('Source changed during validation.')
            return result

        with mock.patch.object(tool.common, 'FRONTIER', self.skill), \
                mock.patch.object(tool, 'validate_state', validate), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = tool.main(['init', str(self.w), '--scope', str(self.scope_path), '--ids', 'N1', 'N2'])
        self.assertNotEqual(code, 0)
        self.assertFalse(self.journal.exists())

    def test_record_reaches_flock_and_waits_before_reading_journal(self):
        self.start()
        path = self.save_debate()
        tool = load_tool('tournoi')
        ctx = multiprocessing.get_context('spawn')
        attempting, read_event, result = ctx.Event(), ctx.Event(), ctx.Queue()
        recorder = ctx.Process(target=locked_recorder, args=(str(self.skill), str(self.w),
                               str(path), attempting, read_event, result))
        try:
            with tool.journal_lock(self.w):
                recorder.start()
                self.assertTrue(attempting.wait(20), 'record did not reach flock')
                self.assertFalse(read_event.wait(0.2), 'record read journal while lock was held')
                self.assertEqual(read_json(self.journal)['matches'], [])
            recorder.join(20)
            self.assertFalse(recorder.is_alive())
            self.assertEqual(recorder.exitcode, 0)
            self.assertEqual(result.get(timeout=5), 0)
            self.assertTrue(read_event.is_set())
            self.assertEqual(len(read_json(self.journal)['matches']), 1)
        finally:
            if recorder.is_alive():
                recorder.terminate()
            if recorder.pid is not None:
                recorder.join()
            result.close()
            result.join_thread()

    def test_author_fallback_and_declared_other_family_are_explicit(self):
        self.start()
        nxt = json.loads(self.cli('next').stdout)
        self.assertIn('author', nxt['instruction'])
        self.assertIn('independence', nxt['instruction'])
        self.assertEqual(self.record().returncode, 0)
        self.assertIn('no configured different-family critic', self.cli('show').stdout)

    def test_other_declared_family_still_does_not_certify_independence(self):
        set_config(self.skill, lambda c: c['critic'].update(families=['other-family']))
        self.start()
        p = self.record(route='critic', judge_family='other-family')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('identity and independence unverified', p.stdout)
        self.assertNotIn('no configured different-family critic', p.stdout)

    def test_saved_outputs_disclose_author_and_same_family_debates(self):
        cases = (('author', 'unknown', [], 'author comparisons', 'author-family'),
                 ('author', 'other-family', ['other-family'], 'author comparisons', 'author-family'),
                 ('critic', 'author-family', [], 'same-family comparisons', 'author-family'),
                 ('critic', 'author-alias', ['author-alias'], 'same-family comparisons', 'author-family'),
                 ('critic', 'author-family', [], 'same-family comparisons', None),
                 ('critic', 'other-family', ['other-family'], None, 'author-family'))
        for route, judge, families, attribution, host in cases:
            with self.subTest(route=route, judge=judge, families=families, host=host):
                for filename in ('tournoi_rebound.json', 'IDEA-CARD.md', 'IDEA-REPORT.md'):
                    (self.w / filename).unlink(missing_ok=True)
                set_config(self.skill, lambda c: c['critic'].update(
                    host_family=host, families=families, aliases={'author-alias': 'author-family'}))
                self.start()
                result = self.record(route=route, judge_family=judge)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                # Give the protocol fixture a valid critic for this configuration;
                # the tournament judge remains the one recorded above.
                different = families == ['other-family']
                mutate(self.w, 'critique.json', lambda d: d.update(
                    author_family='author-family',
                    critic_family='other-family' if different else 'author-family',
                    same_family=not different))
                result = run_tool('card', self.w, tools_dir=self.skill / 'tools')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                card = (self.w / 'IDEA-CARD.md').read_text()
                report = (self.w / 'IDEA-REPORT.md').read_text()
                if attribution:
                    self.assertTrue(attribution + ' carry no independence claim' in card + report,
                                    'missing debate attribution: ' + attribution)
                else:
                    self.assertNotIn('no configured different-family critic used', report)
                self.assertIn('critic identity and independence unverified', report)
                self.assertNotIn('independent critic used', card + report)
                result = run_tool('check', self.w, tools_dir=self.skill / 'tools')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unknown_proposal_links_and_numeric_prose_are_marks(self):
        self.start()
        packet = self.packet()
        d = debate(*packet['pair'])
        d['input_sha256'] = packet['input_sha256']
        d['comparison']['test_ids'] = ['T404']
        d['comparison']['objection'] = 'The model guesses a 70 percent gain.'
        path = self.w / 'debate.json'
        write_json(path, d)
        p = self.cli('record', '--debate', path.relative_to(self.tmp))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('T404', p.stdout)
        self.assertIn('numerical prose unverified', p.stdout)
        p = run_tool('check', self.w)
        self.assertEqual(p.returncode, 0, p.stdout)

    def test_guard_checks_decoded_paths_and_linked_public_context(self):
        # Runtime paths are built from the temporary workspace, never hard coded.
        private_path = str(self.tmp / 'private-notes' / 'source.txt')
        write_json(self.w / 'history.json', {'entries': [{'file': private_path}]})
        data = read_json(self.w / 'hypotheses.json')
        data['hypotheses'][0]['statement'] = 'Consult ' + private_path
        write_json(self.w / 'hypotheses.json', data)
        self.start()
        p = self.cli('pack')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('packet withheld', p.stderr)
        self.assertNotIn(private_path, p.stdout + p.stderr)

    def test_optional_corruption_marks_without_blocking_frontier(self):
        self.journal.write_text('{')
        p = run_tool('check', self.w)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('mark: [TOURNOI]', p.stdout)
        p = run_tool('card', self.w)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('unavailable', (self.w / 'IDEA-CARD.md').read_text())

    def test_card_two_lines_with_top_ids_count_and_full_report(self):
        self.start()
        self.assertEqual(self.record().returncode, 0)
        p = run_tool('card', self.w)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        card = (self.w / 'IDEA-CARD.md').read_text()
        lines = [line for line in card.splitlines() if '[TOURNOI]' in line]
        self.assertGreaterEqual(len(lines), 1)
        self.assertLessEqual(len(lines), 2)
        self.assertLessEqual(len(card.splitlines()), 80)
        for phrase in ('N1', 'debates: 1', 'aggregate of LLM judgments, not a measurement', 'IDEA-REPORT.md'):
            self.assertIn(phrase, ' '.join(lines))
        report = (self.w / 'IDEA-REPORT.md').read_text()
        for phrase in ('objection', 'proposed_change', '1016', '984', 'input_sha256'):
            self.assertIn(phrase, report)
        state = read_json(self.journal)
        state['matches'][0]['comparison']['reason'] += ' Revision.'
        write_json(self.journal, state)
        self.assertIn('[CARD-STALE]', run_tool('check', self.w).stdout)

    def test_documented_opt_in_and_final_statements(self):
        text = (FRONTIER / 'SKILL.md').read_text()
        for phrase in ('OFF', 'debate the ideas', 'compare the ideas by debates',
                       'final before', 'aggregate of LLM judgments, not a measurement',
                       'no restart', 'original statements'):
            self.assertIn(phrase, text)


class DebatesV2Card(V2):
    def test_v2_card_moves_all_tournament_marks_to_report(self):
        w = self.to_v2('valid_vp_rebound')
        for name in ('rebound.json', 'rebound_after.json'):
            mutate(w, name, lambda d: [i.update(search_plan=plan_of(i['id'], i['prior_art']['queries']))
                                       for i in d['ideas']])
        skill = copy_skill(self.tmp, 'tournament-skill')
        set_config(skill, lambda c: c['critic'].update(host_family='claude', families=[]))
        scope_path = w / 'scope.json'
        write_json(scope_path, scope())
        for route, judge, attribution in (('author', 'unknown', 'author comparisons'),
                                           ('critic', 'anthropic', 'same-family comparisons')):
            with self.subTest(route=route, judge=judge):
                (w / 'tournoi_rebound.json').unlink(missing_ok=True)
                p = run_tool('tournoi', 'init', w, '--scope', scope_path,
                             '--ids', 'N1', 'N2', tools_dir=skill / 'tools')
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                p = run_tool('tournoi', 'pack', w, tools_dir=skill / 'tools')
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                packet = json.loads(p.stdout)
                match = debate(*packet['pair'])
                match.update(route=route, judge_family=judge)
                match['input_sha256'] = packet['input_sha256']
                debate_path = w / 'debate.json'
                write_json(debate_path, match)
                p = run_tool('tournoi', 'record', w, '--debate', debate_path,
                             tools_dir=skill / 'tools')
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                state = read_json(w / 'tournoi_rebound.json')
                self.assertEqual(set(state['original_statements']), {'N1', 'N2'})
                self.assertEqual({d['id'] for d in state['source_digests']}, {'N1', 'N2'})
                p = run_tool('card', w, tools_dir=skill / 'tools')
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                card = (w / 'IDEA-CARD.md').read_text()
                lines = [line for line in card.splitlines() if '[TOURNOI]' in line]
                self.assertEqual(len(lines), 1)
                self.assertLessEqual(len(card.splitlines()), 80)
                self.assertIn('debates: 1', lines[0])
                self.assertIn('aggregate of LLM judgments, not a measurement', lines[0])
                report = (w / 'IDEA-REPORT.md').read_text()
                self.assertIn('input_sha256', report)
                self.assertIn('independence unverified', report)
                self.assertIn(attribution + ' carry no independence claim', report)
                self.assertNotIn('independent critic used', card + report)
                p = run_tool('check', w, tools_dir=skill / 'tools')
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
