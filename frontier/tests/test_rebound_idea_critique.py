# SPDX-License-Identifier: Apache-2.0
"""Oracle: individual public critique, bounded author repair, no live VP calls."""
import copy
import json
from unittest import mock

from .helpers import FRONTIER, load_tool, mutate, read_json, run_tool, write_json
from .rb_common import RB, VP, NOVP


class IdeaCritique(RB):
    def setUp(self):
        super().setUp()
        self.w = self.work(NOVP)
        self.tools = self.skill_copy()
        mutate(self.tools.parent, 'config.json', lambda c: c['critic'].update(
            host_family='openai', families=[]))
        mutate(self.w, 'critique.json', lambda d: d.update(author_family='openai', critic_family='openai'))
        self.legacy = read_json(self.w / 'rebound.json')
        self.drop_ranking(NOVP)
        p = run_tool('step', self.w, '--step', 'rebound_critique', tools_dir=self.tools)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.before = read_json(self.w / 'rebound.json')

    def cli(self, command, *args):
        return run_tool('rebound', command, self.w, *args, tools_dir=self.tools)

    def packet(self):
        p = self.cli('pack')
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def submission(self):
        return dict(input_sha256=self.packet()['input_sha256'], author_family='openai', critiques=[
            dict(id=i['id'], objections=['Testability: the control is underspecified.',
                                       'Limits and coherence: the transfer could fail.'],
                 proposed_change='Specify a blinded control to distinguish the mechanism.',
                 route='subagent', critic_family='openai', date='2026-11-17T10:00:00Z')
            for i in self.before['ideas']])

    def record(self, data=None):
        path = self.w / 'incoming-critique.json'
        write_json(path, self.submission() if data is None else data)
        return self.cli('record', '--critique', path)

    def recorded(self):
        p = self.record()
        self.assertEqual(p.returncode, 0, p.stderr)

    def repairs(self):
        return dict(input_sha256=self.packet()['input_sha256'], repairs=[
            dict(id=i['id'], operator=i['operator'], goal=i['mechanism']['goal'],
                 statement=i['statement'] + ' Use a blinded control.',
                 rationale='Addresses objection 1 and the proposed change.', critique_items=[1, 3])
            for i in self.before['ideas']])

    def repair(self, data=None):
        path = self.w / 'incoming-repair.json'
        write_json(path, self.repairs() if data is None else data)
        return self.cli('repair', '--repair', path)

    def test_round2_record_refuses_existing_ranking_or_selection_atomically(self):
        submission = self.submission()
        for keys in (('ranking',), ('selection',), ('ranking', 'selection')):
            with self.subTest(keys=keys):
                data = dict(self.before, **{k: self.legacy[k] for k in keys})
                write_json(self.w / 'rebound.json', data)
                if 'ranking' in keys:
                    submission = self.submission()
                before = (self.w / 'rebound.json').read_bytes()
                result = self.record(submission)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn('before ranking or selection', result.stderr)
                self.assertEqual((self.w / 'rebound.json').read_bytes(), before)

    def test_round2_repair_refuses_existing_ranking_or_selection_atomically(self):
        self.recorded()
        recorded = read_json(self.w / 'rebound.json')
        repairs = self.repairs()
        for keys in (('ranking',), ('selection',), ('ranking', 'selection')):
            with self.subTest(keys=keys):
                # Future ranking keeps the stored critique valid. Test fresh
                # hashes when ranking exists and the early guard for selection alone.
                data = copy.deepcopy(recorded)
                for k in keys:
                    data[k] = copy.deepcopy(self.legacy[k])
                    data[k]['ranked_utc' if k == 'ranking' else 'decided_utc'] = '2099-01-01T00:00:00Z'
                write_json(self.w / 'rebound.json', data)
                if 'ranking' in keys:
                    repairs = self.repairs()
                before = (self.w / 'rebound.json').read_bytes()
                result = self.repair(repairs)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn('before ranking or selection', result.stderr)
                self.assertEqual((self.w / 'rebound.json').read_bytes(), before)

    def test_round2_checker_blocks_critique_after_ranking(self):
        self.recorded()
        mutate(self.w, 'rebound.json', lambda d: d.update(ranking=self.legacy['ranking']))
        self.assertTrue(any(p.startswith(('[REB-ORDER]', '[REB-REPAIR]'))
                            for p in self.check.problems(self.w)))

    def test_round2_checker_blocks_repair_after_ranking(self):
        self.recorded()
        self.assertEqual(self.repair().returncode, 0)
        def change(d):
            d['ranking'] = dict(self.legacy['ranking'], ranked_utc='2026-11-17T10:30:00Z')
            # Isolate repair chronology from critique chronology and schema errors.
            for i in d['ideas']:
                i['repair']['date'] = '2026-11-17T11:00:00Z'
        mutate(self.w, 'rebound.json', change)
        self.assertTrue(any(p.startswith(('[REB-ORDER]', '[REB-REPAIR]')) and 'after ranking' in p
                            for p in self.check.problems(self.w)))

    def test_round2_repair_records_real_utc_date(self):
        self.recorded()
        self.assertEqual(self.repair().returncode, 0)
        tool = load_tool('rebound')
        for idea in read_json(self.w / 'rebound.json')['ideas']:
            self.assertTrue(tool.utc(idea['repair'].get('date')))

    def test_round2_checker_blocks_invalid_or_missing_repair_date(self):
        self.recorded()
        self.assertEqual(self.repair().returncode, 0)
        good = read_json(self.w / 'rebound.json')
        for date in (None, '2026-02-30T10:00:00Z'):
            with self.subTest(date=date):
                data = copy.deepcopy(good)
                if date is None:
                    data['ideas'][0]['repair'].pop('date', None)
                else:
                    data['ideas'][0]['repair']['date'] = date
                write_json(self.w / 'rebound.json', data)
                self.assertTrue(any(p.startswith('[REB-REPAIR]') for p in self.check.problems(self.w)))

    def test_round2_record_date_must_follow_other_ideas_prior_art(self):
        mutate(self.w, 'rebound.json', lambda d: d['ideas'][1]['prior_art'].update(date='2026-11-17T09:00:00Z'))
        submission = self.submission()
        submission['critiques'][0]['date'] = '2026-11-17T08:00:00Z'
        before = (self.w / 'rebound.json').read_bytes()
        self.assertNotEqual(self.record(submission).returncode, 0)
        self.assertEqual((self.w / 'rebound.json').read_bytes(), before)

    def test_round2_checker_date_must_follow_other_ideas_prior_art(self):
        mutate(self.w, 'rebound.json', lambda d: d['ideas'][1]['prior_art'].update(date='2026-11-17T09:00:00Z'))
        self.recorded()
        mutate(self.w, 'rebound.json', lambda d: d['ideas'][0]['critique'].update(date='2026-11-17T08:00:00Z'))
        self.assertTrue(any(p.startswith(('[REB-ORDER]', '[REB-REPAIR]'))
                            for p in self.check.problems(self.w)))

    def test_round2_missing_critic_journal_entry_is_blocking_budget_mark(self):
        self.recorded()
        mutate(self.w, 'run.json', lambda d: d.update(steps=[s for s in d['steps'] if s['step'] != 'rebound_critique']))
        problems, warnings = self.check.run_all(self.w)
        self.assertTrue(any(p.startswith('[BUDGET]') and 'rebound_critique' in p for p in problems),
                        (problems, warnings))
        result = run_tool('check', self.w, tools_dir=self.tools)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('[BUDGET]', result.stdout + result.stderr)

    def test_round2_individual_critique_without_batch_also_needs_journal(self):
        self.recorded()
        mutate(self.w, 'rebound.json', lambda d: d.pop('idea_critique'))
        mutate(self.w, 'run.json', lambda d: d.update(steps=[s for s in d['steps'] if s['step'] != 'rebound_critique']))
        self.assertTrue(any(p.startswith('[BUDGET]') and 'rebound_critique' in p
                            for p in self.check.problems(self.w)))

    def test_round2_legacy_ranked_file_without_critique_remains_valid(self):
        write_json(self.w / 'rebound.json', self.legacy)
        problems, warnings = self.check.run_all(self.w)
        self.assertEqual(problems, [])
        self.assertTrue(any('[REB-CRITIQUE]' in w for w in warnings))

    def test_round2_phase_date_equalities_are_allowed(self):
        latest = max(i['prior_art']['date'] for i in self.before['ideas'])
        submission = self.submission()
        for c in submission['critiques']:
            c['date'] = latest
        self.assertEqual(self.record(submission).returncode, 0)
        self.assertEqual(self.repair().returncode, 0)
        data = read_json(self.w / 'rebound.json')
        for i in data['ideas']:
            i['repair']['date'] = latest
        data['ranking'] = dict(self.legacy['ranking'], ranked_utc=latest)
        write_json(self.w / 'rebound.json', data)
        self.assertEqual(self.check.problems(self.w), [])

    def test_public_packet_exact_idea_whitelist_and_no_comparison(self):
        packet = self.packet()
        self.assertEqual(len(packet['ideas']), len(self.before['ideas']))
        for idea in packet['ideas']:
            self.assertEqual(set(idea), {'id', 'title', 'statement', 'parent_idea', 'domain'})
        self.assertEqual(packet['criteria'], ['coherence', 'testability', 'distinctiveness', 'limits'])
        self.assertNotIn('pair', packet)
        self.assertNotIn(str(self.w), json.dumps(packet))
        self.assertIn('each idea alone', packet['policy'])
        self.assertFalse((self.w / 'idea-critique.json').exists())

    def test_pack_is_read_only(self):
        before = (self.w / 'rebound.json').read_bytes()
        self.packet()
        self.assertEqual((self.w / 'rebound.json').read_bytes(), before)

    def test_missing_critique_is_nonblocking_visible_mark(self):
        p, w = self.check.run_all(self.w)
        self.assertEqual(p, [])
        self.assertTrue(any('[REB-CRITIQUE]' in s for s in w))

    def test_legacy_schema_still_valid(self):
        self.assertEqual(self.check.schema_lite.validate(self.before, read_json(FRONTIER / 'schemas/rebound.json')), [])

    def test_record_retains_everything_and_schema_valid(self):
        self.recorded()
        data = read_json(self.w / 'rebound.json')
        for original, current in zip(self.before['ideas'], data['ideas']):
            self.assertEqual(current['original_statement'], original['statement'])
            self.assertFalse(current['statement_changed'])
            self.assertEqual(len(current['critique']['objections']), 2)
            for key, value in original.items():
                self.assertEqual(current[key], value)
        self.assertEqual(self.check.schema_lite.validate(data, read_json(FRONTIER / 'schemas/rebound.json')), [])
        self.assertFalse(any('[REB-CRITIQUE]' in s for s in self.check.run_all(self.w)[1]))

    def test_invalid_critiques_refuse_atomically(self):
        good = self.submission()
        cases = []
        for key in ('route', 'critic_family', 'date', 'proposed_change'):
            d = copy.deepcopy(good)
            del d['critiques'][0][key]
            cases.append(d)
        for objections in ([], ['one'], ['one', 'two', 'three'], ['  ', 'two'], ['one', 2]):
            d = copy.deepcopy(good)
            d['critiques'][0]['objections'] = objections
            cases.append(d)
        for key, value in (('proposed_change', ' '), ('route', 'winner'), ('critic_family', ' '),
                           ('date', '2026-02-30T10:00:00Z'), ('date', 'yesterday')):
            d = copy.deepcopy(good)
            d['critiques'][0][key] = value
            cases.append(d)
        cases += [dict(good, critiques=good['critiques'][:-1]),
                  dict(good, critiques=good['critiques'] + [good['critiques'][0]])]
        for bad in cases:
            with self.subTest(bad=bad):
                before = (self.w / 'rebound.json').read_bytes()
                self.assertNotEqual(self.record(bad).returncode, 0)
                self.assertEqual((self.w / 'rebound.json').read_bytes(), before)

    def test_stale_packet_refused_on_statement_identity_prior_art_or_parent_change(self):
        good = self.submission()
        for change in (lambda d: d['ideas'][0].update(statement='Changed statement'),
                       lambda d: d['ideas'][0].update(operator='anomaly'),
                       lambda d: d['ideas'][0]['prior_art'].update(scope='A changed scope'),
                       lambda d: d.update(parent_idea='Changed parent')):
            write_json(self.w / 'rebound.json', self.before)
            mutate(self.w, 'rebound.json', change)
            self.assertNotEqual(self.record(good).returncode, 0)

    def test_no_silent_overwrite_of_critique(self):
        self.recorded()
        before = (self.w / 'rebound.json').read_bytes()
        self.assertNotEqual(self.record().returncode, 0)
        self.assertEqual((self.w / 'rebound.json').read_bytes(), before)

    def test_configured_other_family_required_and_aliases_normalised(self):
        mutate(self.tools.parent, 'config.json', lambda c: c['critic'].update(families=['claude']))
        self.assertNotEqual(self.record().returncode, 0)
        d = self.submission()
        for c in d['critiques']:
            c.update(route='critic', critic_family='anthropic')
        self.assertEqual(self.record(d).returncode, 0)

    def test_author_route_is_honest_but_never_separate_context(self):
        d = self.submission()
        for c in d['critiques']:
            c['route'] = 'author'
        self.assertEqual(self.record(d).returncode, 0)
        p, w = self.check.run_all(self.w)
        self.assertEqual(p, [])
        self.assertTrue(any('[REB-CRITIQUE]' in s and 'separate context' in s for s in w))

    def test_critique_requires_registered_prior_art(self):
        mutate(self.w, 'rebound.json', lambda d: d['ideas'][0]['prior_art'].update(queries=[]))
        self.assertNotEqual(self.cli('pack').returncode, 0)

    def test_dates_must_follow_prior_art(self):
        d = self.submission()
        d['critiques'][0]['date'] = '2020-01-01T00:00:00Z'
        self.assertNotEqual(self.record(d).returncode, 0)

    def test_private_archive_context_and_paths_withheld(self):
        phrase = 'secret cobalt orchid glacier sequence'
        for kind in ('history', 'context', 'path'):
            write_json(self.w / 'rebound.json', self.before)
            write_json(self.w / 'history.json', {'entries': [{'excerpt': phrase, 'file': 'private/closed.md'}]})
            write_json(self.w / 'context_candidates.json', {'private': phrase})
            value = 'private/closed.md' if kind == 'path' else phrase
            mutate(self.w, 'rebound.json', lambda d: d['ideas'][0].update(statement=value))
            p = self.cli('pack')
            self.assertNotEqual(p.returncode, 0)
            self.assertNotIn(value, p.stdout + p.stderr)

    def test_repair_unchanged_allowed_and_prior_art_preserved(self):
        self.recorded()
        d = self.repairs()
        d['repairs'][0]['statement'] = self.before['ideas'][0]['statement']
        self.assertEqual(self.repair(d).returncode, 0)
        after = read_json(self.w / 'rebound.json')
        self.assertFalse(after['ideas'][0]['statement_changed'])
        self.assertTrue(after['ideas'][1]['statement_changed'])
        for a, b in zip(self.before['ideas'], after['ideas']):
            self.assertEqual(a['prior_art'], b['prior_art'])
            self.assertEqual(a['operator'], b['operator'])
            self.assertEqual(a['mechanism'], b['mechanism'])
        self.assertEqual(self.check.schema_lite.validate(after, read_json(FRONTIER / 'schemas/rebound.json')), [])

    def test_repair_limit_exact_boundary(self):
        self.recorded()
        d = self.repairs()
        original = self.before['ideas'][0]['statement']
        limit = len(original) * 5 // 4 + 60
        d['repairs'][0]['statement'] = 'x' * limit
        self.assertEqual(self.repair(d).returncode, 0)

    def test_repair_invalid_identity_length_or_critique_link_refused(self):
        self.recorded()
        good = self.repairs()
        for key, value in (('id', 'N99'), ('operator', 'anomaly'), ('goal', 'A different goal'),
                           ('statement', 'x' * (len(self.before['ideas'][0]['statement']) * 5 // 4 + 61)),
                           ('statement', ' '), ('critique_items', []), ('critique_items', [4]),
                           ('rationale', ' ')):
            d = copy.deepcopy(good)
            d['repairs'][0][key] = value
            before = (self.w / 'rebound.json').read_bytes()
            self.assertNotEqual(self.repair(d).returncode, 0, key)
            self.assertEqual((self.w / 'rebound.json').read_bytes(), before)

    def test_repair_without_critique_refused(self):
        self.assertNotEqual(self.repair().returncode, 0)

    def test_stale_repair_refused(self):
        self.recorded()
        d = self.repairs()
        mutate(self.w, 'rebound.json', lambda b: b['ideas'][0]['critique'].update(proposed_change='Changed critique'))
        self.assertNotEqual(self.repair(d).returncode, 0)

    def test_second_repair_does_not_delete_history(self):
        self.recorded()
        self.assertEqual(self.repair().returncode, 0)
        before = (self.w / 'rebound.json').read_bytes()
        self.assertNotEqual(self.repair().returncode, 0)
        self.assertEqual((self.w / 'rebound.json').read_bytes(), before)

    def test_checker_refuses_tampered_repairs_identity_and_status(self):
        self.recorded()
        self.assertEqual(self.repair().returncode, 0)
        good = read_json(self.w / 'rebound.json')
        cases = [lambda i: i.pop('critique'), lambda i: i.update(id='N88'),
                 lambda i: i.update(operator='anomaly'), lambda i: i['mechanism'].update(goal='Changed goal'),
                 lambda i: i.update(statement='x' * 1000), lambda i: i['prior_art'].update(status='Not found')]
        for change in cases:
            write_json(self.w / 'rebound.json', good)
            mutate(self.w, 'rebound.json', lambda d: change(d['ideas'][0]))
            self.assertTrue(any('[REB-REPAIR]' in p for p in self.check.problems(self.w)))

    def test_card_and_report_show_repaired_statement_routes_and_original_scope(self):
        self.recorded()
        d = self.repairs()
        d['repairs'][0]['statement'] = self.before['ideas'][0]['statement'] + ' Use BERT as a blinded control.'
        self.assertEqual(self.repair(d).returncode, 0)
        p = run_tool('card', self.w, tools_dir=self.tools)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        card = (self.w / 'IDEA-CARD.md').read_text()
        self.assertIn(d['repairs'][0]['statement'], card)
        self.assertIn('prior art checked on the original statement', card)
        self.assertIn('5 ideas criticised', card)
        self.assertIn('subagent', card)
        self.assertIn('same family', card)
        self.assertLessEqual(len(card.splitlines()), 80)
        written_report = (self.w / 'IDEA-REPORT.md').read_text()
        self.assertIn(d['repairs'][0]['statement'], written_report)
        self.assertIn('5 ideas criticised', written_report)
        self.assertIn(self.before['ideas'][0]['statement'], written_report)
        tool = load_tool('rebound')
        report = '\n'.join(tool.report_lines(self.w))
        self.assertIn(d['repairs'][0]['statement'], report)
        self.assertIn('5 ideas criticised', report)
        self.assertIn(self.before['ideas'][0]['statement'], report)

    def test_budget_is_configured(self):
        mutate(self.tools.parent, 'config.json', lambda c: c.update(rebound_critiques_max=0))
        self.assertNotEqual(self.record().returncode, 0)

    def test_mutations_hold_tournament_directory_lock_before_reading(self):
        tool = load_tool('rebound')
        tournament = load_tool('tournament')
        events = []
        import sys
        real_read = tool.read_rebound
        def read(*args):
            self.assertEqual(events[-1], 'locked')
            return real_read(*args)
        from contextlib import contextmanager
        @contextmanager
        def lock(work):
            events.append('locked')
            yield
            events.append('unlocked')
        submission = self.submission()
        path = self.w / 'incoming-critique.json'
        write_json(path, submission)
        # Patch the module actually shared by the tools, not another import.
        with mock.patch.object(sys.modules['tournament'], 'journal_lock', lock), \
             mock.patch.object(tool, 'read_rebound', read), \
             mock.patch.dict('os.environ', FRONTIER_HOST_FAMILY='openai', FRONTIER_CRITIC_FAMILIES=''):
            self.assertEqual(tool.main(['record', str(self.w), '--critique', str(path)]), 0)
        self.assertEqual(events, ['locked', 'unlocked'])

    def test_malformed_new_snapshots_are_reported_without_crashing(self):
        self.recorded()
        tool = load_tool('rebound')
        data = read_json(self.w / 'rebound.json')
        for key, value in (('original_prior_art', 'bad'), ('original_identity', []),
                           ('original_statement', 42), ('critique', {'date': []})):
            bad = copy.deepcopy(data)
            bad['ideas'][0][key] = value
            with self.subTest(key=key):
                problems, marks = tool.check_data(bad, tool.common.config())
                self.assertTrue(problems)

    def test_source_or_privacy_inventory_change_invalidates_packet(self):
        good = self.submission()
        for filename, value in (('intake.json', dict(read_json(self.w / 'intake.json'), domain='Changed public domain')),
                                ('context_candidates.json', {'private': 'unrelated secret not present in packet'})):
            old = (self.w / filename).read_bytes() if (self.w / filename).exists() else None
            write_json(self.w / filename, value)
            self.assertNotEqual(self.record(good).returncode, 0)
            if old is None:
                (self.w / filename).unlink()
            else:
                (self.w / filename).write_bytes(old)

    def test_removing_an_idea_after_critique_is_refused(self):
        self.recorded()
        mutate(self.w, 'rebound.json', lambda d: d['ideas'].pop())
        self.assertCode('[REB-REPAIR]', NOVP)


class IdeaCritiqueDocs(RB):
    def test_numbered_step_scope_budget_and_owner_choice(self):
        text = (FRONTIER / 'SKILL.md').read_text()
        section = text.split('## 8. ', 1)[1].split('## 8-ter.', 1)[0]
        self.assertLess(section.index('3. **Prior art'), section.index('4. **Critique and repair'))
        self.assertLess(section.index('4. **Critique and repair'), section.index('5. **Ranking'))
        for phrase in ('measured on 30 neighbouring ideas with model judges: ideas criticised then repaired were more often judged worth pursuing; novelty did not move; not a measurement of this run',
                       'one extra critic call for all ideas together', 'rebound_critiques_max',
                       'part of the rebound', 'not a separate option', 'separate context'):
            self.assertIn(phrase, section)
        self.assertIn('test-protocol critique', text)

    def test_step_budget_enforced_from_config(self):
        w = self.work(NOVP)
        tools = self.skill_copy()
        mutate(tools.parent, 'config.json', lambda c: c.update(rebound_critiques_max=2))
        for _ in range(2):
            p = run_tool('step', w, '--step', 'rebound_critique', tools_dir=tools)
            self.assertEqual(p.returncode, 0, p.stderr)
        p = run_tool('step', w, '--step', 'rebound_critique', tools_dir=tools)
        self.assertEqual(p.returncode, 1)
        p = run_tool('check', w, tools_dir=tools)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
