#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Small home-made validator for the subset of JSON Schema used by frontier/schemas/*.json. Standard library only.

Keywords: type (string, integer, number, boolean, object, array, null, or a list of them), required, properties,
additionalProperties (boolean), items, enum, const, minItems, maxItems, minLength, maxLength, pattern (re.search),
minimum, exclusiveMinimum (numeric, draft 7), maximum, $ref (local "#/definitions/<name>" only), and the annotations description, title, definitions, $schema,
$comment, examples. Any other keyword is an error of the schema (ValueError), never silently ignored.

Import: validate(instance, schema) -> list of "path: message" strings (empty = valid).
Command line: schema_lite.py SCHEMA.json FILE.json   (exit 1 when invalid)
"""
import json
import math
import re
import sys

KNOWN = {'type', 'required', 'properties', 'additionalProperties', 'items', 'enum', 'const', 'minItems', 'maxItems',
         'minLength', 'maxLength', 'pattern', 'minimum', 'exclusiveMinimum', 'maximum', '$ref', 'description', 'title', 'definitions',
         '$schema', '$comment', 'examples'}


def _is_type(value, name):
    if name == 'string':
        return isinstance(value, str)
    if name == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    if name == 'number':
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and (isinstance(value, int) or math.isfinite(value)))
    if name == 'boolean':
        return isinstance(value, bool)
    if name == 'object':
        return isinstance(value, dict)
    if name == 'array':
        return isinstance(value, list)
    if name == 'null':
        return value is None
    raise ValueError('unknown type in schema: %r' % name)


def _resolve(ref, root):
    if not ref.startswith('#/definitions/'):
        raise ValueError('only local refs "#/definitions/<name>" are supported: %r' % ref)
    name = ref[len('#/definitions/'):]
    try:
        return root['definitions'][name]
    except KeyError:
        raise ValueError('unresolved ref %r' % ref)


def _walk(value, schema, root, path, errs):
    unknown = set(schema) - KNOWN
    if unknown:
        raise ValueError('unsupported schema keyword(s) at %s: %s' % (path or '$', ', '.join(sorted(unknown))))
    if '$ref' in schema:
        _walk(value, _resolve(schema['$ref'], root), root, path, errs)
    where = path or '$'
    if 'type' in schema:
        types = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        if not any(_is_type(value, t) for t in types):
            errs.append('%s: expected %s, got %s' % (where, ' or '.join(types), type(value).__name__))
            return
    if 'enum' in schema and value not in schema['enum']:
        errs.append('%s: %r not in %r' % (where, value, schema['enum']))
    if 'const' in schema and value != schema['const']:
        errs.append('%s: must be %r' % (where, schema['const']))
    if isinstance(value, str):
        if 'minLength' in schema and len(value.strip()) < schema['minLength']:
            errs.append('%s: shorter than %d characters (spaces aside)' % (where, schema['minLength']))
        if 'maxLength' in schema and len(value) > schema['maxLength']:
            errs.append('%s: longer than %d characters' % (where, schema['maxLength']))
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            errs.append('%s: %r does not match %s' % (where, value, schema['pattern']))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if 'exclusiveMinimum' in schema and value <= schema['exclusiveMinimum']:
            errs.append('%s: not above exclusive minimum %r' % (where, schema['exclusiveMinimum']))
        if 'minimum' in schema and value < schema['minimum']:
            errs.append('%s: below minimum %r' % (where, schema['minimum']))
        if 'maximum' in schema and value > schema['maximum']:
            errs.append('%s: above maximum %r' % (where, schema['maximum']))
    if isinstance(value, list):
        if 'minItems' in schema and len(value) < schema['minItems']:
            errs.append('%s: fewer than %d items' % (where, schema['minItems']))
        if 'maxItems' in schema and len(value) > schema['maxItems']:
            errs.append('%s: more than %d items' % (where, schema['maxItems']))
        if 'items' in schema:
            for i, item in enumerate(value):
                _walk(item, schema['items'], root, '%s[%d]' % (path, i), errs)
    if isinstance(value, dict):
        for key in schema.get('required', []):
            if key not in value:
                errs.append('%s: missing required field %r' % (where, key))
        props = schema.get('properties', {})
        for key, sub in props.items():
            if key in value:
                _walk(value[key], sub, root, '%s.%s' % (path, key) if path else key, errs)
        if schema.get('additionalProperties') is False:
            for key in value:
                if key not in props:
                    errs.append('%s: unexpected field %r' % (where, key))


def validate(instance, schema):
    errs = []
    _walk(instance, schema, schema, '', errs)
    return errs


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0 if argv and argv[0] in ('-h', '--help') else 2
    with open(argv[0], encoding='utf-8') as f:
        schema = json.load(f)
    with open(argv[1], encoding='utf-8') as f:
        data = json.load(f)
    errs = validate(data, schema)
    for e in errs:
        print(e)
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main())
