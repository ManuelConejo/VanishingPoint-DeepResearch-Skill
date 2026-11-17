# SPDX-License-Identifier: Apache-2.0
"""schema_lite.py: the small home-made JSON-schema validator (regression specification R5)."""
import unittest

from .helpers import load_tool


class SchemaLiteTest(unittest.TestCase):
    def setUp(self):
        self.v = load_tool('schema_lite').validate

    def test_type(self):
        self.assertEqual(self.v(3, {'type': 'integer'}), [])
        self.assertTrue(self.v('3', {'type': 'integer'}))
        self.assertTrue(self.v(True, {'type': 'integer'}), 'a boolean is not an integer')
        self.assertEqual(self.v(None, {'type': ['string', 'null']}), [])
        self.assertEqual(self.v(2.5, {'type': 'number'}), [])

    def test_required_properties_additional(self):
        s = {'type': 'object', 'required': ['a'], 'properties': {'a': {'type': 'string'}}, 'additionalProperties': False}
        self.assertEqual(self.v({'a': 'x'}, s), [])
        self.assertTrue(any('a' in e for e in self.v({}, s)))
        self.assertTrue(any('b' in e for e in self.v({'a': 'x', 'b': 1}, s)))
        self.assertTrue(self.v({'a': 1}, s))

    def test_array(self):
        s = {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 2}
        self.assertEqual(self.v(['a'], s), [])
        self.assertTrue(self.v([], s))
        self.assertTrue(self.v(['a', 'b', 'c'], s))
        self.assertTrue(self.v(['a', 1], s))

    def test_string_constraints(self):
        s = {'type': 'string', 'minLength': 2, 'maxLength': 4, 'pattern': '^[a-z]+$'}
        self.assertEqual(self.v('abc', s), [])
        self.assertTrue(self.v('a', s))
        self.assertTrue(self.v('abcde', s))
        self.assertTrue(self.v('ABC', s))

    def test_enum_const_numbers(self):
        self.assertTrue(self.v('x', {'enum': ['a', 'b']}))
        self.assertEqual(self.v('a', {'enum': ['a', 'b']}), [])
        self.assertTrue(self.v('b', {'const': 'a'}))
        self.assertTrue(self.v(0, {'type': 'integer', 'minimum': 1}))
        self.assertTrue(self.v(5, {'type': 'integer', 'maximum': 4}))

    def test_local_ref_and_paths(self):
        s = {'definitions': {'ref': {'type': 'object', 'required': ['id']}},
             'type': 'object', 'properties': {'r': {'type': 'array', 'items': {'$ref': '#/definitions/ref'}}}}
        errs = self.v({'r': [{'id': 'x'}, {}]}, s)
        self.assertEqual(len(errs), 1)
        self.assertIn('r[1]', errs[0])

    def test_unknown_keyword_is_an_error_of_the_schema(self):
        with self.assertRaises(ValueError):
            self.v(1, {'oneOf': []})


if __name__ == '__main__':
    unittest.main()
