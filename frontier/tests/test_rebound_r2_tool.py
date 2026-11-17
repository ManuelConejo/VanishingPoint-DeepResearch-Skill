# SPDX-License-Identifier: Apache-2.0
"""Round 2: `rebound.py select` goes through the same gate as tools/check.py, and keeps what it replaces (regression specification RB45)."""
from .helpers import read_json
from .rb_common import VP
from .test_rebound_tool import ToolBase


class SelectGateTest(ToolBase):
    def sel(self, *args):
        return self.cli('select', self.work(VP), '--file', 'rebound.json', '--utc', '2026-11-14T16:00:00Z', *args)

    def test_refused_when_an_idea_has_no_registered_search(self):
        self.mut(VP, lambda d: d.pop('selection'))
        self.idea(VP, 'N3', lambda i: i['prior_art'].update(queries=[]))
        r = self.sel('--by', 'user', '--retain', 'N1')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('select refused', r.stdout)
        self.assertNotIn('selection', read_json(self.work(VP) / 'rebound.json'))

    def test_refused_when_a_query_is_not_in_the_gateway_journal(self):
        self.mut(VP, lambda d: d.pop('selection'))
        self.idea(VP, 'N1', lambda i: i['prior_art']['queries'].append('never sent to the gateway at all'))
        r = self.sel('--by', 'user', '--retain', 'N2')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('REB-PRIOR-ART', r.stdout)
        self.assertNotIn('selection', read_json(self.work(VP) / 'rebound.json'))

    def test_still_accepted_when_the_directory_is_in_order(self):
        self.mut(VP, lambda d: d.pop('selection'))
        r = self.sel('--by', 'user', '--retain', 'N1')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class SelectHistoryTest(ToolBase):
    def sel(self, *args):
        return self.cli('select', self.work(VP), '--file', 'rebound.json', '--utc', '2026-11-14T16:00:00Z', *args)

    def test_a_replaced_selection_is_kept(self):
        old = read_json(self.work(VP) / 'rebound.json')['selection']
        r = self.sel('--by', 'user', '--retain', 'N2')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = read_json(self.work(VP) / 'rebound.json')
        self.assertEqual(d['selection']['retained'], ['N2'])
        self.assertEqual(d['selection_history'], [old])

    def test_history_grows_and_check_accepts_it(self):
        self.sel('--by', 'user', '--retain', 'N2')
        self.sel('--by', 'user', '--retain', 'N4')
        d = read_json(self.work(VP) / 'rebound.json')
        self.assertEqual(len(d['selection_history']), 2)
        self.assertEqual(self.check.problems(self.work(VP)), [])

    def test_first_selection_has_no_history(self):
        self.mut(VP, lambda d: d.pop('selection'))
        self.sel('--by', 'user', '--retain', 'N1')
        self.assertNotIn('selection_history', read_json(self.work(VP) / 'rebound.json'))
