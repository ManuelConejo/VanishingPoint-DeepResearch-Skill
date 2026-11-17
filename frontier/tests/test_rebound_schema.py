# SPDX-License-Identifier: Apache-2.0
"""Schemas and configuration of the rebound step (regression specification RB3, RB4)."""
import copy
import json
import unittest

from .helpers import FIXTURES, FRONTIER, TempCase, load_tool, read_json
from .rb_common import NOVP, VP

schema_lite = None


def sl():
    global schema_lite
    if schema_lite is None:
        schema_lite = load_tool('schema_lite')
    return schema_lite


def schema(name):
    return read_json(FRONTIER / 'schemas' / (name + '.json'))


IDEA_REQUIRED = ('id', 'title', 'statement', 'operator', 'recurring_ingredient', 'materials', 'mechanism', 'hypothesis', 'test',
                 'prior_art', 'feasibility', 'teaches', 'tradeoffs')
OPERATORS = ('facet_recombination', 'analogy', 'literature_bridge', 'anomaly', 'revived_old_idea', 'hypothesis_inversion',
             'morphological_analysis')


class SchemaFilesTest(unittest.TestCase):
    def test_exist_and_parse(self):
        for n in ('rebound', 'idea_tree', 'rebound_baseline'):
            with self.subTest(schema=n):
                self.assertTrue((FRONTIER / 'schemas' / (n + '.json')).exists())
                schema(n)

    def test_fixtures_valid(self):
        for name, f in ((VP, 'rebound.json'), (VP, 'rebound_after.json'), (NOVP, 'rebound.json')):
            with self.subTest(dir=name, file=f):
                self.assertEqual(sl().validate(read_json(FIXTURES / name / f), schema('rebound')), [])
        self.assertEqual(sl().validate(read_json(FIXTURES / 'IDEA-TREE.json'), schema('idea_tree')), [])
        for p in sorted((FIXTURES / 'export_rebound').glob('[bc]_*.json')):
            with self.subTest(baseline=p.name):
                self.assertEqual(sl().validate(read_json(p), schema('rebound_baseline')), [])

    def test_required_fields_of_an_idea(self):
        base = read_json(FIXTURES / VP / 'rebound.json')
        for key in IDEA_REQUIRED:
            with self.subTest(key=key):
                d = copy.deepcopy(base)
                d['ideas'][0].pop(key)
                self.assertTrue(sl().validate(d, schema('rebound')))

    def test_required_fields_of_the_file(self):
        base = read_json(FIXTURES / VP / 'rebound.json')
        for key in ('stage', 'generated_utc', 'parent_idea', 'ideas', 'duplicate_groups'):
            with self.subTest(key=key):
                d = copy.deepcopy(base)
                d.pop(key)
                self.assertTrue(sl().validate(d, schema('rebound')))

    def test_operator_enum_is_the_documented_one(self):
        s = schema('rebound')
        enum = s['definitions']['idea']['properties']['operator']['enum']
        self.assertEqual(sorted(enum), sorted(OPERATORS))

    def test_prior_art_statuses(self):
        s = schema('rebound')
        enum = s['definitions']['prior_art']['properties']['status']['enum']
        self.assertEqual(sorted(enum), sorted(['Exists', 'Partially', 'Not found', 'Insufficient search']))
        for key in ('status', 'queries', 'scope', 'date', 'closest_work'):
            self.assertIn(key, s['definitions']['prior_art']['required'])

    def test_no_numeric_field_but_the_amount(self):
        found = []

        def walk(node, path):
            if isinstance(node, dict):
                if node.get('type') in ('number', 'integer') or (isinstance(node.get('type'), list)
                                                                  and ('number' in node['type'] or 'integer' in node['type'])):
                    found.append(path)
                for k, v in node.items():
                    walk(v, path + '.' + k)
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, '%s[%d]' % (path, i))
        walk(schema('rebound'), '$')
        self.assertTrue(all(p.endswith('amount') for p in found), found)

    def test_idea_tree_schema(self):
        tree = read_json(FIXTURES / 'IDEA-TREE.json')
        for key in ('id', 'parent', 'idea', 'dir', 'status', 'created_utc'):
            with self.subTest(key=key):
                d = copy.deepcopy(tree)
                d['nodes'][1].pop(key)
                self.assertTrue(sl().validate(d, schema('idea_tree')))
        d = copy.deepcopy(tree)
        d['nodes'][1]['status'] = 'great'
        self.assertTrue(sl().validate(d, schema('idea_tree')))
        statuses = schema('idea_tree')['definitions']['node']['properties']['status']['enum']
        for st in ('active', 'proposed', 'retained', 'rejected', 'pursued', 'abandoned'):
            self.assertIn(st, statuses)

    def test_baseline_schema(self):
        b = read_json(FIXTURES / 'export_rebound' / 'c_01.json')
        # modified round 2 (RB34): the baseline names its parent idea and its generation time
        for key in ('arm', 'parent_idea', 'T', 'generated_utc', 'ideas'):
            with self.subTest(key=key):
                d = copy.deepcopy(b)
                d.pop(key)
                self.assertTrue(sl().validate(d, schema('rebound_baseline')))
        d = copy.deepcopy(b)
        d['arm'] = 'A'
        self.assertTrue(sl().validate(d, schema('rebound_baseline')))

    def test_baseline_has_no_prior_art_field(self):
        # round 2 (RB33): prior art is evaluated apart, by one procedure for the three arms
        props = schema('rebound_baseline')['definitions']['idea']['properties']
        self.assertNotIn('prior_art', props)
        self.assertEqual(schema('rebound_baseline')['definitions']['reference']['type'], 'object')
        self.assertEqual(props['references']['items'], {'$ref': '#/definitions/reference'})

    def test_selection_history_is_in_the_schema(self):
        self.assertIn('selection_history', schema('rebound')['properties'])


class ConfigTest(unittest.TestCase):
    def test_rebound_section(self):
        cfg = read_json(FRONTIER / 'config.json')
        self.assertEqual(cfg['rebound'], {
            'ideas_min': 5, 'ideas_max': 10, 'after_min': 2, 'after_max': 4, 'max_per_operator': 2, 'max_retained': 2,
            'duplicate_overlap': 0.6, 'prior_art_checks_max': 10, 'prior_art_checks_card_max': 14})   # round 2: RB32, RB42

    def test_no_public_seed_anywhere(self):
        self.assertNotIn('seed', read_json(FRONTIER / 'config.json')['rebound'])
        for rel in ('SKILL.md', 'README.md'):
            self.assertNotIn('20261114', (FRONTIER / rel).read_text(encoding='utf-8'), rel)

    def test_budget_untouched(self):
        self.assertEqual(read_json(FRONTIER / 'config.json')['budget'], {'vp_runs': 3, 'critiques': 1, 'executions': 1})

    def test_common_config_has_defaults(self):
        common = load_tool('common')
        cfg = common.config()
        self.assertEqual(cfg['rebound']['ideas_max'], 10)
        self.assertEqual(cfg['budget'], {'vp_runs': 3, 'critiques': 1, 'executions': 1})


if __name__ == '__main__':
    unittest.main()
