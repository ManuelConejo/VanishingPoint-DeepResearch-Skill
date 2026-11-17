# SPDX-License-Identifier: Apache-2.0
"""V2-1 .. V2-5 of regression specification: version marker, the approved framing, the work that waits for it, archives only with data."""
import json
from pathlib import Path

from .helpers import TempCase, load_tool
from .v2_common import V2, VP, mutate, read_json, run_tool, write_json


class VersionTest(TempCase):
    def test_new_run_stamps_version_4_and_is_v2_and_r3(self):
        guards = load_tool('guards')
        r = run_tool('new_run', 'a bare idea about titles', '--parent', self.tmp, '--date', '2026-11-14')
        self.assertEqual(r.returncode, 0, r.stderr)
        d = Path(r.stdout.strip())
        self.assertEqual(read_json(d / 'frontier-version.json'), {'frontier_version': 4})
        self.assertTrue(guards.is_v2(d))
        self.assertTrue(guards.is_r3(d))

    def test_older_directories_are_not_v2(self):
        guards = load_tool('guards')
        self.assertFalse(guards.is_v2(self.fx / 'valid_vp'))
        d = self.tmp / 'r3dir'
        d.mkdir()
        write_json(d / 'frontier-version.json', {'frontier_version': 3})
        self.assertTrue(guards.is_r3(d))
        self.assertFalse(guards.is_v2(d))


class FramingToolTest(V2):
    def new(self):
        w = self.to_r3()
        mutate(w, 'intake.json', lambda d: d.update(frontier_version=4))
        return w

    def propose(self, w, *extra, drop=()):
        args = ['propose', w, '--objective', 'Measure the retrieval effect of shortening a preprint title',
                '--success', 'A paired test separates retrieval from prestige', '--constraint', 'Offline index only',
                '--refuted-by', 'No rank difference between the variants', '--no-free-draft', 'fixture']
        for d in drop:
            i = args.index(d)
            del args[i:i + 2]
        return run_tool('framing', *args, *extra)

    def test_propose_writes_four_fields_hash_and_time(self):
        w = self.new()
        r = self.propose(w)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        f = read_json(w / 'framing.json')
        p = f['proposal']
        for k in ('objective', 'success_criterion', 'constraints', 'refuted_by'):
            self.assertTrue(p[k], k)
        self.assertRegex(f['proposal_sha256'], '^[0-9a-f]{64}$')
        self.assertIsNone(f['approval'])
        self.assertEqual(f['free_phase'], {'skipped': 'fixture'})

    def test_every_field_is_required_and_no_placeholder(self):
        for drop in ('--objective', '--success', '--constraint', '--refuted-by'):
            with self.subTest(drop=drop):
                self.fresh()
                w = self.new()
                r = self.propose(w, drop=(drop,))
                self.assertNotEqual(r.returncode, 0)
                self.assertFalse((w / 'framing.json').exists())
        self.fresh()
        w = self.new()
        r = run_tool('framing', 'propose', w, '--objective', 'tbd', '--success', 'n/a', '--constraint', 'none',
                     '--refuted-by', '-', '--no-free-draft', 'fixture')
        self.assertEqual(r.returncode, 1)

    def test_free_phase_first(self):
        w = self.new()
        r = run_tool('framing', 'propose', w, '--objective', 'Measure the retrieval effect of shortening a preprint title',
                     '--success', 'A paired test separates retrieval from prestige', '--constraint', 'Offline index only',
                     '--refuted-by', 'No rank difference between the variants')
        self.assertEqual(r.returncode, 1)
        self.assertIn('free_draft.md', r.stderr + r.stdout)
        (w / 'free_draft.md').write_text('Everything I know about titles and retrieval, in no format.\n', encoding='utf-8')
        r = run_tool('step', w, '--step', 'free_draft')
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run_tool('framing', 'propose', w, '--objective', 'Measure the retrieval effect of shortening a preprint title',
                     '--success', 'A paired test separates retrieval from prestige', '--constraint', 'Offline index only',
                     '--refuted-by', 'No rank difference between the variants')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read_json(w / 'framing.json')['free_phase'], {'draft': 'free_draft.md'})

    def test_approve_keeps_the_proposal_and_needs_a_reply(self):
        w = self.new()
        self.propose(w)
        self.assertEqual(run_tool('framing', 'approve', w).returncode, 2)
        r = run_tool('framing', 'approve', w, '--reply', 'Yes, that is what I want.')
        self.assertEqual(r.returncode, 0, r.stderr)
        f = read_json(w / 'framing.json')
        self.assertEqual(f['approval']['status'], 'approved')
        self.assertEqual(f['approval']['by'], 'user')
        self.assertEqual(f['approval']['reply'], 'Yes, that is what I want.')
        self.assertEqual(f['final'], f['proposal'])

    def test_correct_changes_fields_and_lists_them(self):
        w = self.new()
        self.propose(w)
        r = run_tool('framing', 'correct', w, '--reply', 'The criterion must name the sample.')
        self.assertEqual(r.returncode, 1, 'a correction that changes nothing is refused')
        r = run_tool('framing', 'correct', w, '--reply', 'The criterion must name the sample.',
                     '--success', 'A paired test on 200 records separates retrieval from prestige')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        f = read_json(w / 'framing.json')
        self.assertEqual(f['approval']['status'], 'corrected')
        self.assertEqual(f['approval']['changes'], ['success_criterion'])
        self.assertIn('200 records', f['final']['success_criterion'])
        self.assertEqual(f['final']['objective'], f['proposal']['objective'])
        self.assertEqual(f['approval']['reply'], 'The criterion must name the sample.')

    def test_assume_is_marked_and_not_approved(self):
        w = self.new()
        self.propose(w)
        r = run_tool('framing', 'assume', w)
        self.assertEqual(r.returncode, 0, r.stderr)
        a = read_json(w / 'framing.json')['approval']
        self.assertEqual((a['status'], a['by']), ('assumption', 'assumption'))
        self.assertIn('ASSUMED', a['reply'])

    def test_a_second_decision_is_refused(self):
        w = self.new()
        self.propose(w)
        run_tool('framing', 'assume', w)
        self.assertEqual(run_tool('framing', 'approve', w, '--reply', 'Yes, go.').returncode, 1)


class FramingGateTest(V2):
    def test_work_steps_wait_for_the_framing(self):
        w = self.to_r3()
        mutate(w, 'intake.json', lambda d: d.update(frontier_version=4))
        for step in ('vp_run', 'prior_art', 'hypotheses', 'tests', 'critique', 'research_plan'):
            with self.subTest(step=step):
                extra = ['--vp-run', 'prior_art'] if step == 'vp_run' else []
                before = (w / 'run.json').read_text(encoding='utf-8')
                r = run_tool('step', w, '--step', step, *extra)
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertIn('framing', r.stderr)
                self.assertEqual((w / 'run.json').read_text(encoding='utf-8'), before)

    def test_unapproved_proposal_does_not_open_the_gate(self):
        w = self.to_r3()
        mutate(w, 'intake.json', lambda d: d.update(frontier_version=4))
        run_tool('framing', 'propose', w, '--objective', 'Measure the retrieval effect of shortening a preprint title',
                 '--success', 'A paired test separates retrieval from prestige', '--constraint', 'Offline index only',
                 '--refuted-by', 'No rank difference', '--no-free-draft', 'fixture')
        self.assertEqual(run_tool('step', w, '--step', 'tests').returncode, 1)
        run_tool('framing', 'approve', w, '--reply', 'Yes, go ahead.')
        self.assertEqual(run_tool('step', w, '--step', 'tests').returncode, 0)

    def test_framing_step_itself_and_older_directories_are_not_gated(self):
        w = self.to_r3()
        self.assertEqual(run_tool('step', w, '--step', 'tests').returncode, 0, 'an R3 directory keeps its behaviour')
        self.assertEqual(run_tool('step', w, '--step', 'framing').returncode, 0)


class FramingCheckTest(V2):
    def test_the_baseline_is_clean(self):
        self.to_v2()
        self.assertV2Clean()

    def test_missing_framing_blocks(self):
        w = self.to_v2()
        (w / 'framing.json').unlink()
        self.assertBlocks('[FRAMING]')

    def test_unapproved_framing_blocks(self):
        w = self.to_v2()
        mutate(w, 'framing.json', lambda d: d.update(approval=None, final=None))
        self.assertBlocks('[FRAMING]')

    def test_an_approved_framing_whose_text_differs_from_the_proposal_blocks(self):
        w = self.to_v2()
        mutate(w, 'framing.json', lambda d: d['final'].update(objective='Know something quite different from the proposal'))
        self.assertBlocks('[FRAMING]')

    def test_a_changed_proposal_after_approval_blocks(self):
        w = self.to_v2()

        def go(d):
            d['proposal']['objective'] = 'Another objective written after the user approved the first one'
            d['final']['objective'] = d['proposal']['objective']
        mutate(w, 'framing.json', go)
        self.assertBlocks('[FRAMING]')

    def test_a_user_approval_without_a_reply_blocks(self):
        w = self.to_v2()
        mutate(w, 'framing.json', lambda d: d['approval'].update(reply=''))
        self.assertBlocks('[FRAMING]')

    def test_assumed_framing_passes_and_is_marked_on_the_card(self):
        w = self.to_v2()
        self.fresh()
        w = self.to_r3()
        mutate(w, 'intake.json', lambda d: d.update(frontier_version=4))
        self.framing(w, 'assume')
        a = read_json(w / 'framing.json')['approval']
        self.assertEqual(a['status'], 'assumption')

    def test_corrected_framing_passes(self):
        self.to_r3()
        w = self.work()
        mutate(w, 'intake.json', lambda d: d.update(frontier_version=4))
        self.framing(w, 'correct')
        self.assertEqual(read_json(w / 'framing.json')['approval']['status'], 'corrected')

    def test_order_in_run_json_is_marked_not_blocked(self):
        w = self.to_v2()

        def go(d):
            s = [x for x in d['steps'] if x['step'] == 'framing']
            d['steps'] = [x for x in d['steps'] if x['step'] != 'framing'] + s
        mutate(w, 'run.json', go)
        self.assertMarks('[FRAMING-ORDER]')

    def test_archives_checked_must_match_project_dirs(self):
        w = self.to_v2()
        mutate(w, 'framing.json', lambda d: d['archives'].update(checked=True))
        self.assertBlocks('[FRAMING]')

    def test_without_project_dirs_the_framing_says_not_checked_and_nothing_is_penalised(self):
        w = self.to_v2()
        f = read_json(w / 'framing.json')
        self.assertFalse(f['archives']['checked'])
        self.assertIn('not checked', f['archives']['note'])
        self.assertEqual([p for p in self.v2_probs() if 'HISTORY' in p], [])
        self.assertEqual([x for x in self.warns() if 'HISTORY' in x], [])
