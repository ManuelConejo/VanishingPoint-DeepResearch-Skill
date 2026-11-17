# SPDX-License-Identifier: Apache-2.0
"""AM30-AM44: the project context, key numbers, power on the real numbers, the idea tree kept between sessions."""
import json
import os

from .am1_common import AM, NOVP, REBOUND, VP, load_tool, mutate, read_json, run_tool, write_json
from .helpers import copy_skill, set_config


def numbers(*rows):
    return [dict(name=n, value=v, source='user', confirmed=True, **extra) for n, v, extra in rows]


class ContextSchemaTest(AM):
    def test_am30_block_accepted(self):
        ctx = {"objective": "Compare felt sleeves for painted wooden tile packing",
               "data_available": ["tile inspection sheets", "tile dimensions"],
               "constraints": ["no extra workshop equipment", "include preparation time"],
               "key_numbers": [{"name": "n_periods", "value": 60, "unit": "periods", "source": "user", "confirmed": True}]}
        self.set_intake(VP, lambda d: d.update(context=ctx))
        self.assertNoCode('[SCHEMA]')
        self.assertClean()

    def test_am30_non_numeric_refused(self):
        ctx = {"key_numbers": [{"name": "n_periods", "value": "sixty", "source": "user"}]}
        self.set_intake(VP, lambda d: d.update(context=ctx))
        self.assertCode('[SCHEMA] intake.json')

    def test_am30_absent_changes_nothing(self):
        self.assertClean()


class ExtractTest(AM):
    def intake_with(self, name=VP):
        root = self.project()
        self.set_intake(name, lambda d: d.update(project_dirs=[str(root)]))
        return root

    def extract(self, name=VP):
        r = run_tool('context', 'extract', self.work(name), '--json')
        return r

    def cands(self, name=VP):
        return read_json(self.work(name) / 'context_candidates.json')['candidates']

    def test_am31_candidates_with_file_and_line(self):
        self.intake_with()
        r = self.extract()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        c = self.cands()
        got = {(x['class'], x['value'], x['file'], x['line']) for x in c}
        self.assertIn(('n_periods', 60, 'README.md', 2), got)
        self.assertIn(('n_units', 2300, 'README.md', 3), got)
        self.assertIn(('ic', 0.046, 'README.md', 4), got)
        self.assertIn(('cost', 17, 'README.md', 5), got)
        self.assertIn(('sharpe', 2.41, 'README.md', 6), got)
        self.assertIn(('n_periods', 48, 'results/results-2026-q3.md', 2), got)
        self.assertIn(('cost', 23, 'lessons/LESSONS.md', 2), got)
        for x in c:
            self.assertTrue(x['id'].startswith('C'))
            self.assertLessEqual(len(x['excerpt']), 200)

    def test_am31_only_readme_results_lessons_are_read(self):
        self.intake_with()
        self.extract()
        self.assertFalse([x for x in self.cands() if x['file'] == 'notes.md'])

    def test_am31_deterministic(self):
        self.intake_with()
        self.extract()
        a = (self.work() / 'context_candidates.json').read_text(encoding='utf-8')
        self.extract()
        self.assertEqual(a, (self.work() / 'context_candidates.json').read_text(encoding='utf-8'))

    def test_am32_no_project_dirs_refused(self):
        r = self.extract()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse((self.work() / 'context_candidates.json').exists())

    def test_am32_unnamed_folder_never_read(self):
        root = self.project()
        other = self.tmp / 'other'
        other.mkdir()
        (other / 'README.md').write_text('We use 123 periods here.\n', encoding='utf-8')
        self.set_intake(VP, lambda d: d.update(project_dirs=[str(root)]))
        self.extract()
        self.assertFalse([x for x in self.cands() if x['value'] == 123])

    def test_am33_confirm(self):
        self.intake_with()
        self.extract()
        cid = [x for x in self.cands() if x['class'] == 'n_periods' and x['value'] == 60][0]['id']
        r = run_tool('context', 'confirm', self.work(), '--id', cid, '--name', 'n_periods')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        kn = read_json(self.work() / 'intake.json')['context']['key_numbers']
        self.assertEqual(len(kn), 1)
        self.assertEqual((kn[0]['name'], kn[0]['value'], kn[0]['source'], kn[0]['cited'], kn[0]['confirmed']),
                         ('n_periods', 60, 'extracted', 'README.md:2', True))
        self.assertNoCode('[CONTEXT')

    def test_am33_unknown_id_and_no_value_flag(self):
        self.intake_with()
        self.extract()
        r = run_tool('context', 'confirm', self.work(), '--id', 'C999', '--name', 'n_periods')
        self.assertNotEqual(r.returncode, 0)
        r = run_tool('context', 'confirm', self.work(), '--id', 'C1', '--name', 'n_periods', '--value', '5')
        self.assertNotEqual(r.returncode, 0)

    def test_am34_add_by_user(self):
        r = run_tool('context', 'add', self.work(), '--name', 'sd', '--value', '0.35', '--role', 'sd', '--by', 'user')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        kn = read_json(self.work() / 'intake.json')['context']['key_numbers']
        self.assertEqual((kn[0]['name'], kn[0]['value'], kn[0]['source'], kn[0]['confirmed']), ('sd', 0.35, 'user', True))
        r = run_tool('context', 'add', self.work(), '--name', 'x', '--value', 'abc', '--by', 'user')
        self.assertNotEqual(r.returncode, 0)

    def test_am35_cite_must_hold(self):
        root = self.intake_with()
        self.extract()
        cid = [x for x in self.cands() if x['class'] == 'n_periods' and x['value'] == 60][0]['id']
        run_tool('context', 'confirm', self.work(), '--id', cid, '--name', 'n_periods')
        (root / 'README.md').write_text("# Synthetic tile inspection\nWe pack tiles monthly over 72 periods.\n", encoding='utf-8')
        self.assertCode('[CONTEXT-CITE]')

    def test_am35_unconfirmed_extracted_refused(self):
        self.intake_with()
        ctx = {"key_numbers": [{"name": "n_periods", "value": 60, "source": "extracted", "cited": "README.md:2",
                                "confirmed": False}]}
        self.set_intake(VP, lambda d: d.update(context=ctx))
        self.assertCode('[CONTEXT-CONFIRM]')

    def test_am41_candidates_stay_local(self):
        self.intake_with()
        self.extract()
        gw = self.work('vp_prior_art') / 'state' / 'journal.jsonl'
        line = json.loads(gw.read_text(encoding='utf-8').splitlines()[0])
        line['query'] = 'We inspect painted tiles over 60 periods (15 years) handling cost'
        with open(str(gw), 'a', encoding='utf-8') as f:
            f.write(json.dumps(line) + '\n')
        self.assertAnyLeak()

    def assertAnyLeak(self):
        p = self.probs()
        self.assertTrue(any(x.startswith('[HISTORY-LEAK]') or x.startswith('[CONTEXT-LEAK]') for x in p), p)


class SimContextTest(AM):
    def with_context(self, rows):
        self.set_intake(VP, lambda d: d.update(context={"key_numbers": rows}))

    def sim(self, *args, name=VP):
        r = run_tool('sim', *args)
        return r, (json.loads(r.stdout) if r.returncode == 0 else None)

    BASE = ('--design', 'paired', '--scenario', 'H1=0.2', '--scenario', 'R1=0', '--expect', 'H1=continue',
            '--expect', 'R1=stop', '--continue-if-lower-above', '0', '--stop-if-upper-below', '0.1')

    def test_am36_uses_context(self):
        self.with_context(numbers(('n_periods', 60, {}), ('sd', 0.35, {'role': 'sd'})))
        r, out = self.sim(*self.BASE, '--context', self.work())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((out['n'], out['sd']), (60, 0.35))
        c = out['context']
        self.assertTrue(c['used'])
        self.assertEqual(c['inputs']['n']['name'], 'n_periods')
        self.assertEqual(c['inputs']['sd']['value'], 0.35)
        self.assertEqual(c['not_from_context'], [])

    def test_am36_explicit_role_wins_over_name(self):
        self.with_context(numbers(('window', 48, {'role': 'n'}), ('n_periods', 60, {'role': 'other'}),
                                  ('sd', 0.5, {})))
        r, out = self.sim(*self.BASE, '--context', self.work())
        self.assertEqual(out['n'], 48)

    def test_am36_unconfirmed_never_used(self):
        self.with_context([{"name": "n_periods", "value": 60, "source": "assumption", "confirmed": False},
                           {"name": "sd", "value": 0.35, "source": "user", "confirmed": True}])
        r, out = self.sim(*self.BASE, '--n', '30', '--context', self.work())
        self.assertEqual(out['n'], 30)
        self.assertIn('n', out['context']['not_from_context'])

    def test_am37_says_when_no_context(self):
        r, out = self.sim(*self.BASE, '--n', '40', '--sd', '0.5')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(out['context']['used'])
        self.assertIn('no project context', out['context']['note'])

    def test_am37_context_without_the_number_says_so(self):
        self.with_context(numbers(('sd', 0.35, {})))
        r, out = self.sim(*self.BASE, '--n', '40', '--context', self.work())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('n', out['context']['not_from_context'])
        self.assertIn('sd', out['context']['inputs'])
        self.assertIn('n', out['context']['missing'])

    def test_missing_n_is_an_error(self):
        r, out = self.sim(*self.BASE, '--sd', '0.5')
        self.assertEqual(r.returncode, 2)

    def test_am38_command_line_wins_and_divergence_written(self):
        self.with_context(numbers(('n_periods', 60, {}), ('sd', 0.35, {})))
        r, out = self.sim(*self.BASE, '--n', '30', '--context', self.work())
        self.assertEqual(out['n'], 30)
        self.assertIn('n', out['context']['differs'])
        self.assertEqual(out['context']['differs']['n']['context'], 60)
        self.assertEqual(out['context']['differs']['n']['command_line'], 30)
        self.assertIn('sd', out['context']['inputs'])

    def test_am40_needed_n(self):
        r, a = self.sim('--design', 'means', '--needed-n', '--effect', '0.5', '--sd', '1.0')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(a['mode'], 'needed_n')
        self.assertTrue(55 <= a['needed_n'] <= 80, a)
        self.assertGreaterEqual(a['power_at_n'], 0.78)
        self.assertTrue(a['verified_by_simulation'])
        r, b = self.sim('--design', 'means', '--needed-n', '--effect', '0.5', '--sd', '1.0')
        self.assertEqual(a, b)
        fresh = load_tool('sim').rerun_needed_n(a)
        self.assertEqual(load_tool('sim').compare_needed_n(a, fresh), [])

    def test_am40_paired_and_proportions(self):
        r, a = self.sim('--design', 'paired', '--needed-n', '--effect', '0.5', '--sd', '1.0')
        self.assertTrue(26 <= a['needed_n'] <= 42, a)
        r, b = self.sim('--design', 'proportions', '--needed-n', '--effect', '0.1', '--base', '0.5')
        self.assertTrue(350 <= b['needed_n'] <= 470, b)

    def test_am40_needed_n_uses_context_sd(self):
        self.with_context(numbers(('sd', 1.0, {})))
        r, a = self.sim('--design', 'means', '--needed-n', '--effect', '0.5', '--context', self.work())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(a['context']['used'])
        self.assertEqual(a['sd'], 1.0)

    def test_am39_sim_must_carry_the_context_value(self):
        self.with_context(numbers(('n_periods', 200, {}), ('sd', 5.0, {})))
        def go(d):
            s = d['tests'][0]['sensitivity']['simulation']
            s['context'] = {"used": True, "inputs": {"n": {"name": "n_periods", "value": 60}}, "not_from_context": ["sd"]}
        self.mut(VP, 'tests.json', go)
        self.assertCode('[CONTEXT-SIM]')

    def test_am39_sim_with_the_right_value_passes(self):
        self.with_context(numbers(('n_periods', 200, {}), ('sd', 5.0, {})))
        def go(d):
            s = d['tests'][0]['sensitivity']['simulation']
            s['context'] = {"used": True, "inputs": {"n": {"name": "n_periods", "value": 200},
                                                     "sd": {"name": "sd", "value": 5.0}}, "not_from_context": []}
        self.mut(VP, 'tests.json', go)
        self.assertNoCode('[CONTEXT-SIM]')

    def test_am39_context_power_warning(self):
        self.with_context(numbers(('n_periods', 60, {})))
        w = self.check.warnings(self.work())
        self.assertTrue(any(x.startswith('[CONTEXT-POWER]') for x in w), w)

    def test_am39_no_warning_without_context(self):
        w = self.check.warnings(self.work())
        self.assertFalse(any(x.startswith('[CONTEXT-POWER]') for x in w))

    def test_am44_card_line(self):
        self.with_context(numbers(('n_periods', 60, {}), ('sd', 0.35, {})))
        r = self.card()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        t = (self.work() / 'IDEA-CARD.md').read_text(encoding='utf-8')
        line = [l for l in t.splitlines() if l.startswith('Context')]
        self.assertEqual(len(line), 1, t)
        self.assertIn('2 key numbers', line[0])
        self.assertIn("not tied to the project's numbers", line[0])
        self.assertLessEqual(len(t.splitlines()), 80)


class TreeDirTest(AM):
    def skill(self, **cfg):
        sk = copy_skill(self.tmp / 'sk')
        set_config(sk, lambda c: c.update(cfg))
        return sk / 'tools'

    def test_am94_config_defaults(self):
        c = load_tool('common').config()
        for k in ('tree_dir', 'catalogue', 'directions_index'):
            self.assertIn(k, c)
            self.assertIsNone(c[k])
        self.assertIn('context', c)
        self.assertIn('matter', c)
        self.assertIn('moment', c)

    def test_am94_environment_overrides(self):
        import importlib
        old = {k: os.environ.get(k) for k in ('FRONTIER_TREE_DIR', 'FRONTIER_CATALOGUE', 'FRONTIER_DIRECTIONS_INDEX')}
        try:
            os.environ.update(FRONTIER_TREE_DIR='/x/tree', FRONTIER_CATALOGUE='/x/cat.tsv', FRONTIER_DIRECTIONS_INDEX='/x/dir.tsv')
            c = load_tool('common').config()
            self.assertEqual((c['tree_dir'], c['catalogue'], c['directions_index']), ('/x/tree', '/x/cat.tsv', '/x/dir.tsv'))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def register(self, work, tools, env=None):
        return run_tool('rebound', 'tree', work, '--register', tools_dir=tools, env=env)

    def test_am42_configured_dir_is_used_and_created(self):
        store = self.tmp / 'store' / 'trees'
        tools = self.skill(tree_dir=str(store))
        r = self.register(self.work(REBOUND), tools)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((store / 'IDEA-TREE.json').exists())

    def test_am42_rebound_file_field_wins(self):
        store = self.tmp / 'store'
        tools = self.skill(tree_dir=str(store))
        explicit = self.tmp / 'explicit.json'
        self.mut(REBOUND, 'rebound.json', lambda d: d.update(tree=str(explicit)))
        r = self.register(self.work(REBOUND), tools)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(explicit.exists())
        self.assertFalse((store / 'IDEA-TREE.json').exists())

    def test_am42_without_config_parent_dir_is_kept(self):
        mod = load_tool('rebound')
        self.assertEqual(mod.tree_path(self.work(REBOUND), {}), self.work(REBOUND).resolve().parent / 'IDEA-TREE.json')

    def test_am42_env_dir(self):
        store = self.tmp / 'envstore'
        env = dict(os.environ, FRONTIER_TREE_DIR=str(store))
        r = self.register(self.work(REBOUND), None, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((store / 'IDEA-TREE.json').exists())

    def test_am43_tree_survives_two_sessions(self):
        store = self.tmp / 'sessions'
        env = dict(os.environ, FRONTIER_TREE_DIR=str(store))
        self.assertEqual(self.register(self.work(REBOUND), None, env=env).returncode, 0)
        first = read_json(store / 'IDEA-TREE.json')
        # a second session, another working directory (a fresh copy of the same fixture under another name)
        import shutil
        shutil.copytree(str(self.work(REBOUND)), str(self.fx / 'session2'))
        r = self.register(self.fx / 'session2', None, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        second = read_json(store / 'IDEA-TREE.json')
        self.assertGreater(len(second['nodes']), len(first['nodes']))
        roots = [n for n in second['nodes'] if n.get('parent') is None]
        self.assertEqual(len(roots), 2)
        r = run_tool('rebound', 'tree', self.fx / 'session2', '--check', env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
