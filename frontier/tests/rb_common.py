# SPDX-License-Identifier: Apache-2.0
"""Shared helpers of the rebound tests (regression specification): mutation of one idea, assertions on check.py codes, a skill copy
whose config.json is changed. No network, no model, no container."""
import copy
import json

from .helpers import TempCase, copy_skill, load_tool, mutate, read_json, run_tool, set_config, write_json

VP = 'valid_vp_rebound'
NOVP = 'valid_novp_rebound'


class RB(TempCase):
    def setUp(self):
        super().setUp()
        self.check = load_tool('check')

    def probs(self, name=VP):
        return self.check.problems(self.work(name))

    def codes(self, name=VP):
        return ' | '.join(self.probs(name))

    def assertCode(self, code, name=VP):
        probs = self.probs(name)
        self.assertTrue(any(p.startswith(code) for p in probs), '%s not in %r' % (code, probs))
        return probs

    def assertNoCode(self, code, name=VP):
        probs = self.probs(name)
        self.assertFalse(any(p.startswith(code) for p in probs), '%s in %r' % (code, probs))

    def assertAnyCode(self, codes, name=VP):
        probs = self.probs(name)
        self.assertTrue(any(p.startswith(c) for p in probs for c in codes), '%r not in %r' % (codes, probs))

    def idea(self, work_name, iid, fn, fname='rebound.json'):
        def go(d):
            for it in d['ideas']:
                if it['id'] == iid:
                    fn(it)
                    return
            raise KeyError(iid)
        mutate(self.work(work_name), fname, go)

    def mut(self, work_name, fn, fname='rebound.json'):
        mutate(self.work(work_name), fname, fn)

    def drop_ranking(self, name=VP):
        """No ranking and no choice (round 2, RB42: an unchecked idea forbids both); the tree follows the file."""
        self.mut(name, lambda d: (d.pop('ranking', None), d.pop('selection', None)))
        if (self.fx / 'IDEA-TREE.json').exists():
            mutate(self.fx, 'IDEA-TREE.json', lambda d: [n.update(status='proposed') for n in d['nodes']
                                                         if n['status'] in ('retained', 'rejected')])

    def skill_copy(self, **rebound):
        """A copy of the skill whose config.json 'rebound' section is changed; returns (tools_dir)."""
        self._copies = getattr(self, '_copies', 0) + 1
        sk = copy_skill(self.tmp / ('skillcopy%d' % self._copies))

        def cfg(c):
            c.setdefault('rebound', {}).update(rebound)
        set_config(sk, cfg)
        return sk / 'tools'

    def run_copy(self, tool, tools_dir, *args):
        return run_tool(tool, *args, tools_dir=tools_dir)
