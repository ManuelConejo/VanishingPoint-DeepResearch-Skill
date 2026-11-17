# SPDX-License-Identifier: Apache-2.0
"""tools/rebound.py (mechanical aid), tools/step.py new steps (regression specification RB4, RB13, RB14, RB22, RB23, RB24)."""
import copy
import json
import shutil

from .helpers import FIXTURES, load_tool, mutate, read_json, run_tool, write_json
from .rb_common import NOVP, RB, VP


class ToolBase(RB):
    def cli(self, *args, tools=None):
        """Runs tools/rebound.py (never named "run": that would hide unittest's TestCase.run and skip every test)."""
        return run_tool('rebound', *args, tools_dir=tools) if tools else run_tool('rebound', *args)

    def jrun(self, *args, tools=None):
        r = self.cli(*args, tools=tools)
        try:
            return r, json.loads(r.stdout)
        except ValueError:
            self.fail('not JSON: %r %r' % (r.stdout, r.stderr))


class HelpTest(ToolBase):
    def test_help_and_usage(self):
        r = self.cli('--help')
        self.assertEqual(r.returncode, 0)
        for sub in ('groups', 'quotas', 'tree', 'select', 'link'):
            self.assertIn(sub, r.stdout)
        self.assertEqual(self.cli().returncode, 2)
        self.assertEqual(self.cli('groups', str(self.tmp / 'nowhere')).returncode, 2)


class GroupsTest(ToolBase):
    def dup(self):
        src = read_json(self.work(VP) / 'rebound.json')['ideas'][0]['mechanism']['summary']
        self.idea(VP, 'N2', lambda i: i['mechanism'].update(summary=src))

    def test_no_group_on_valid(self):
        r, out = self.jrun('groups', self.work(VP), '--json')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(out['groups'], [])

    def test_group_found_and_reported(self):
        self.dup()
        r, out = self.jrun('groups', self.work(VP), '--json')
        self.assertEqual(r.returncode, 1)   # exit 1: duplicates to report
        self.assertEqual([(g['ids'], g['fields']) for g in out['groups']], [(['N1', 'N2'], ['mechanism'])])

    def test_write_records_the_groups_and_changes_nothing_else(self):
        self.dup()
        before = read_json(self.work(VP) / 'rebound.json')
        r = self.cli('groups', self.work(VP), '--write')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        after = read_json(self.work(VP) / 'rebound.json')
        self.assertEqual(after['duplicate_groups'], [{'ids': ['N1', 'N2'], 'fields': ['mechanism']}])
        before['duplicate_groups'] = after['duplicate_groups']
        self.assertEqual(before, after)   # no idea removed, nothing else touched
        self.assertNoCode('[REB-DUP]')
        r2 = self.cli('groups', self.work(VP), '--write')   # idempotent
        self.assertEqual(read_json(self.work(VP) / 'rebound.json'), after)

    def test_word_overlap_and_threshold_from_config(self):
        base = read_json(self.work(VP) / 'rebound.json')['ideas'][0]['mechanism']['summary']
        self.idea(VP, 'N2', lambda i: i['mechanism'].update(summary=base + ' with extra rival wording'))
        r, out = self.jrun('groups', self.work(VP), '--json')
        self.assertEqual(len(out['groups']), 1)
        self.assertIn('mechanism', out['groups'][0]['fields'])
        tools = self.skill_copy(duplicate_overlap=0.95)
        r, out = self.jrun('groups', self.work(VP), '--json', tools=tools)
        self.assertEqual(out['groups'], [])
        tools = self.skill_copy(duplicate_overlap=0.0)
        r, out = self.jrun('groups', self.work(VP), '--json', tools=tools)
        self.assertEqual(len(out['groups']), 1)   # everything overlaps: one group of all five ideas
        self.assertEqual(len(out['groups'][0]['ids']), 5)

    def test_groups_by_chain(self):
        src = read_json(self.work(VP) / 'rebound.json')['ideas'][0]
        self.idea(VP, 'N2', lambda i: i['mechanism'].update(summary=src['mechanism']['summary']))
        self.idea(VP, 'N3', lambda i: i['hypothesis'].update(statement=src['hypothesis']['statement']))
        r, out = self.jrun('groups', self.work(VP), '--json')
        self.assertEqual([g['ids'] for g in out['groups']], [['N1', 'N2', 'N3']])
        self.assertEqual(out['groups'][0]['fields'], ['hypothesis', 'mechanism'])

    def test_file_option(self):
        r, out = self.jrun('groups', self.work(VP), '--file', 'rebound_after.json', '--json')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(out['groups'], [])

    def test_stopwords_alone_do_not_group(self):
        self.idea(VP, 'N2', lambda i: i['test'].update(one_line='The of and for with that this from into.'))
        self.idea(VP, 'N1', lambda i: i['test'].update(one_line='The and of for with that this from into.'))
        r, out = self.jrun('groups', self.work(VP), '--json')
        self.assertEqual(out['groups'], [])


class QuotasTest(ToolBase):
    def test_valid(self):
        r, out = self.jrun('quotas', self.work(VP), '--json')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(out['ideas'], 5)
        self.assertEqual(out['limits'], {'min': 5, 'max': 10, 'per_operator': 2})
        self.assertEqual(out['per_operator']['facet_recombination'], 1)
        self.assertEqual(out['violations'], [])

    def test_step_8_bis_limits(self):
        r, out = self.jrun('quotas', self.work(VP), '--file', 'rebound_after.json', '--json')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(out['limits'], {'min': 2, 'max': 4, 'per_operator': 2})

    def test_violations(self):
        self.mut(VP, lambda d: d['ideas'].pop())
        r, out = self.jrun('quotas', self.work(VP), '--json')
        self.assertEqual(r.returncode, 1)
        self.assertTrue(out['violations'])
        self.fresh()
        for k in ('N4', 'N5'):
            self.idea(VP, k, lambda i: i.update(operator='facet_recombination'))
        r, out = self.jrun('quotas', self.work(VP), '--json')
        self.assertEqual(r.returncode, 1)
        self.assertIn('facet_recombination', ' '.join(out['violations']))

    def test_limits_come_from_config(self):
        tools = self.skill_copy(ideas_min=6)
        r, out = self.jrun('quotas', self.work(VP), '--json', tools=tools)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(out['limits']['min'], 6)

    def test_human_output(self):
        r = self.cli('quotas', self.work(VP))
        self.assertEqual(r.returncode, 0)
        self.assertIn('5 ideas', r.stdout)


class TreeTest(ToolBase):
    def own_tree(self):
        (self.fx / 'IDEA-TREE.json').unlink()

    def test_register_gives_the_fixture_tree(self):
        want = read_json(FIXTURES / 'IDEA-TREE.json')
        self.own_tree()
        r = self.cli('tree', self.work(VP), '--register')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read_json(self.fx / 'IDEA-TREE.json'), want)

    def test_register_is_idempotent(self):
        self.own_tree()
        self.cli('tree', self.work(VP), '--register')
        first = (self.fx / 'IDEA-TREE.json').read_bytes()
        self.cli('tree', self.work(VP), '--register')
        self.assertEqual((self.fx / 'IDEA-TREE.json').read_bytes(), first)

    def test_register_keeps_the_status_set_since(self):
        self.own_tree()
        self.cli('tree', self.work(VP), '--register')
        mutate(self.fx, 'IDEA-TREE.json', lambda d: [n.update(status='abandoned') for n in d['nodes'] if n['id'] == 'I4'])
        self.cli('tree', self.work(VP), '--register')
        node = [n for n in read_json(self.fx / 'IDEA-TREE.json')['nodes'] if n['id'] == 'I4'][0]
        self.assertEqual(node['status'], 'abandoned')

    def test_shared_between_two_directories(self):
        self.own_tree()
        self.cli('tree', self.work(VP), '--register')
        other = self.fx / 'second_idea'
        shutil.copytree(str(self.work(NOVP)), str(other))
        r = self.cli('tree', other, '--register')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        t = read_json(self.fx / 'IDEA-TREE.json')
        ids = [n['id'] for n in t['nodes']]
        self.assertEqual(len(ids), len(set(ids)))
        roots = [n for n in t['nodes'] if n['parent'] is None]
        self.assertEqual(sorted(n['dir'] for n in roots), ['second_idea', 'valid_vp_rebound'])
        self.assertEqual(len([n for n in t['nodes'] if n['dir'] == 'second_idea']), 6)

    def test_node_content(self):
        t = read_json(FIXTURES / 'IDEA-TREE.json')
        n = [x for x in t['nodes'] if x['source'] and x['source']['idea_id'] == 'N3'][0]
        self.assertEqual(n['operator'], 'literature_bridge')
        self.assertIs(n['recurring_ingredient'], True)
        self.assertEqual(n['parent'], 'I1')
        self.assertIn('arxiv:2101.00001', n['materials'])
        self.assertEqual(n['status'], 'proposed')

    def test_check_valid_and_broken(self):
        r = self.cli('tree', self.work(VP), '--check')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cases = {
            'duplicate id': lambda d: d['nodes'][2].update(id='I2'),
            'missing parent': lambda d: d['nodes'][2].update(parent='I99'),
            'cycle': lambda d: d['nodes'][0].update(parent='I3'),
            'unknown status': lambda d: d['nodes'][2].update(status='great'),
            'self parent': lambda d: d['nodes'][1].update(parent='I2'),
        }
        for name, fn in cases.items():
            with self.subTest(name):
                self.fresh()
                mutate(self.fx, 'IDEA-TREE.json', fn)
                r = self.cli('tree', self.work(VP), '--check')
                self.assertEqual(r.returncode, 1, name)

    def test_tree_option_and_missing_tree(self):
        self.own_tree()
        r = self.cli('tree', self.work(VP), '--check')
        self.assertEqual(r.returncode, 2)
        custom = self.tmp / 'elsewhere.json'
        r = self.cli('tree', self.work(VP), '--register', '--tree', custom)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(custom.exists())


class SelectTest(ToolBase):
    def fresh_selection(self):
        self.mut(VP, lambda d: d.pop('selection'))

    def sel(self, *args):
        return self.cli('select', self.work(VP), '--file', 'rebound.json', '--utc', '2026-11-14T16:00:00Z', *args)

    def test_retain_and_reject(self):
        self.fresh_selection()
        r = self.sel('--by', 'user', '--retain', 'N1', '--reject', 'N2=Needs data that is not at hand.')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = read_json(self.work(VP) / 'rebound.json')
        self.assertEqual(d['selection'], {'retained': ['N1'], 'rejected': [{'id': 'N2', 'reason': 'Needs data that is not at hand.'}],
                                          'decided_by': 'user', 'decided_utc': '2026-11-14T16:00:00Z'})
        tree = read_json(self.fx / 'IDEA-TREE.json')
        st = {n['source']['idea_id']: n['status'] for n in tree['nodes'] if n['source'] and n['source']['file'] == 'rebound.json'}
        self.assertEqual(st['N1'], 'retained')
        self.assertEqual(st['N2'], 'rejected')
        self.assertEqual(st['N3'], 'proposed')
        self.assertEqual(self.probs(), [])

    def test_refusals(self):
        self.fresh_selection()
        for args in (['--by', 'user', '--retain', 'N1', '--retain', 'N3', '--retain', 'N4'],
                     ['--by', 'user', '--retain', 'N9'],
                     ['--by', 'assumption', '--retain', 'N1'],
                     ['--by', 'user', '--retain', 'N1', '--reject', 'N1=Both at once is not allowed.'],
                     ['--by', 'user', '--reject', 'N2=short']):
            with self.subTest(args=args):
                r = self.sel(*args)
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertNotIn('selection', read_json(self.work(VP) / 'rebound.json'))

    def test_needs_the_ranking_and_its_time(self):
        self.fresh_selection()
        self.mut(VP, lambda d: d.pop('ranking'))
        self.assertEqual(self.sel('--by', 'user', '--retain', 'N1').returncode, 1)
        self.fresh()
        self.fresh_selection()
        r = self.cli('select', self.work(VP), '--file', 'rebound.json', '--utc', '2026-11-14T13:50:00Z', '--by', 'user',
                     '--retain', 'N1')
        self.assertEqual(r.returncode, 1)

    def test_assumption_retains_nothing(self):
        self.fresh_selection()
        r = self.sel('--by', 'assumption')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read_json(self.work(VP) / 'rebound.json')['selection']['retained'], [])


class LinkTest(ToolBase):
    def child(self):
        c = self.fx / 'child_idea'
        c.mkdir()
        write_json(c / 'intake.json', read_json(self.work(NOVP) / 'intake.json'))
        return c

    def test_child_is_linked_to_its_mother(self):
        c = self.child()
        r = self.cli('link', self.work(VP), '--file', 'rebound.json', '--idea', 'N1', '--child-dir', c)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        t = read_json(self.fx / 'IDEA-TREE.json')
        mother = [n for n in t['nodes'] if n['source'] and n['source']['idea_id'] == 'N1' and n['source']['file'] == 'rebound.json'][0]
        kid = [n for n in t['nodes'] if n['dir'] == 'child_idea'][0]
        self.assertEqual(kid['parent'], mother['id'])
        self.assertEqual(kid['status'], 'active')
        self.assertEqual(mother['status'], 'pursued')
        self.assertEqual(kid['idea'], read_json(c / 'intake.json')['idea'])
        self.assertTrue(read_json(self.fx / 'IDEA-TREE.json')['nodes'])
        self.assertEqual(self.cli('tree', self.work(VP), '--check').returncode, 0)
        self.assertEqual(self.probs(), [])   # pursued is consistent with a retained idea

    def test_only_a_retained_idea_can_be_pursued(self):
        c = self.child()
        r = self.cli('link', self.work(VP), '--file', 'rebound.json', '--idea', 'N3', '--child-dir', c)
        self.assertEqual(r.returncode, 1)
        r = self.cli('link', self.work(VP), '--file', 'rebound.json', '--idea', 'N1', '--child-dir', self.fx / 'nowhere')
        self.assertEqual(r.returncode, 2)

    def test_link_twice_is_refused(self):
        c = self.child()
        self.cli('link', self.work(VP), '--file', 'rebound.json', '--idea', 'N1', '--child-dir', c)
        r = self.cli('link', self.work(VP), '--file', 'rebound.json', '--idea', 'N1', '--child-dir', c)
        self.assertEqual(r.returncode, 1)


class RepeatTest(ToolBase):
    """RB31: the repetition test, three rebounds from the same seed idea; the share of ideas found again."""

    def copies(self, n=3):
        out = []
        for k in range(n):
            p = self.tmp / ('run%d.json' % k)
            shutil.copyfile(str(self.work(VP) / 'rebound.json'), str(p))
            out.append(p)
        return out

    def test_identical_runs_find_everything_again(self):
        a, b, c = self.copies()
        r, out = self.jrun('repeat', a, b, c, '--json')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(out['runs'], 3)
        self.assertEqual(out['overall_share'], 1.0)
        self.assertEqual([x['found_again'] for x in out['per_run']], [5, 5, 5])
        self.assertEqual([x['ideas'] for x in out['per_run']], [5, 5, 5])

    def test_disjoint_runs_find_nothing_again(self):
        a, b = self.copies(2)
        r, out = self.jrun('repeat', a, self.work(VP) / 'rebound_after.json', '--json')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(out['overall_share'], 0.0)

    def test_partial_overlap(self):
        a, b, c = self.copies()

        def edit(p):
            d = read_json(p)
            for i in d['ideas'][:2]:
                i['title'] = 'Zeta ' + i['id'] + ' quasar nebula'
                i['statement'] = 'Orbit planet comet galaxy ' + i['id']
                i['mechanism']['summary'] = 'Lunar tidal wavelength amplitude spectrum ' + i['id']
                i['hypothesis']['statement'] = 'Solar flux isotope plasma ' + i['id']
                i['test']['one_line'] = 'Telescope calibration photometry exposure ' + i['id']
            write_json(p, d)
        edit(c)
        r, out = self.jrun('repeat', a, b, c, '--json')
        found = {x['file']: x['found_again'] for x in out['per_run']}
        self.assertEqual(sorted(found.values()), [3, 5, 5])   # c finds 3 again in a and b; a and b find all 5 in each other
        self.assertEqual(out['threshold'], 0.6)

    def test_directories_are_accepted(self):
        r, out = self.jrun('repeat', self.work(VP), self.work(NOVP), '--json')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(out['runs'], 2)

    def test_threshold_from_config(self):
        a, b = self.copies(2)
        d = read_json(b)
        d['ideas'][0]['mechanism']['summary'] += ' with extra rival wording'
        write_json(b, d)
        tools = self.skill_copy(duplicate_overlap=0.99)
        r, out = self.jrun('repeat', a, b, '--json', tools=tools)
        self.assertEqual(r.returncode, 0)
        self.assertLess(out['per_run'][0]['found_again'], 5 + 1)
        self.assertEqual(out['threshold'], 0.99)

    def test_usage(self):
        a, = self.copies(1)
        self.assertEqual(self.cli('repeat', a).returncode, 2)
        self.assertEqual(self.cli('repeat', a, self.tmp / 'nowhere.json').returncode, 2)
        (self.tmp / 'bad.json').write_text('{oops', encoding='utf-8')
        self.assertEqual(self.cli('repeat', a, self.tmp / 'bad.json').returncode, 2)

    def test_human_output_reports_shares_not_scores(self):
        a, b, c = self.copies()
        r = self.cli('repeat', a, b, c)
        self.assertEqual(r.returncode, 0)
        self.assertIn('found again', r.stdout)
        self.assertNotRegex(r.stdout, r'(?i)novelty')


class StepTest(ToolBase):
    def step(self, *args):
        return run_tool('step', self.work(VP), *args)

    def test_new_steps(self):
        self.assertEqual(self.step('--step', 'rebound').returncode, 0)
        self.assertEqual(self.step('--step', 'rebound_vp_run').returncode, 2)   # needs --vp-run
        self.assertEqual(self.step('--step', 'rebound_vp_run', '--vp-run', 'rb_n1').returncode, 0)
        steps = read_json(self.work(VP) / 'run.json')['steps']
        self.assertEqual(steps[-1]['step'], 'rebound_vp_run')

    def test_budget_of_rebound_vp_runs(self):
        used = sum(1 for s in read_json(self.work(VP) / 'run.json')['steps'] if s['step'] == 'rebound_vp_run')
        self.assertEqual(used, 7)
        for _ in range(14 - used):      # modified round 2 (RB42): 14 per card (prior_art_checks_card_max)
            self.assertEqual(self.step('--step', 'rebound_vp_run', '--vp-run', 'rb_n1').returncode, 0)
        r = self.step('--step', 'rebound_vp_run', '--vp-run', 'rb_n1')
        self.assertEqual(r.returncode, 1)
        self.assertIn('budget', r.stderr)

    def test_budget_comes_from_config(self):
        tools = self.skill_copy(prior_art_checks_card_max=8)
        r = run_tool('step', self.work(VP), '--step', 'rebound_vp_run', '--vp-run', 'rb_n1', tools_dir=tools)
        self.assertEqual(r.returncode, 0)   # 8 allowed, 7 used
        r = run_tool('step', self.work(VP), '--step', 'rebound_vp_run', '--vp-run', 'rb_n1', tools_dir=tools)
        self.assertEqual(r.returncode, 1)

    def test_old_budgets_unchanged(self):
        run_tool('step', self.work('valid_novp'), '--step', 'critique')
        r = run_tool('step', self.work('valid_novp'), '--step', 'critique')
        self.assertEqual(r.returncode, 1)
