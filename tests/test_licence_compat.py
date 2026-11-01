#!/usr/bin/env python3
"""Offline tests of licence-compat (tools/sources/licence_compat.py, data tools/licence_compat.json):
  1. served with plugins/code.md (enabled_by github), refused otherwise; no network (access local, no host);
  2. the disclaimer (not legal advice) opens every answer; X = receiving project, Y = code taken (not symmetric);
  3. verdicts from the table with their rule and sources: permissive into GPL (conditions), GPL into permissive (incompatible), Apache-2.0
     into GPL-2.0-only (incompatible) and into GPL-3.0 (conditions, NOTICE), deprecated aliases (GPL-3.0 = GPL-3.0-only);
  4. expressions: Y "A OR B" keeps the best option, X "A OR B" needs every option, AND needs every licence; WITH exceptions unknown;
  5. never compatible by default: an unknown licence, an uncovered pair, a licence published on/after T -> unknown with its reason;
  6. the table is data: a malformed file (duplicate cell, unknown condition, rule without source) is refused; another table changes the
     answers without touching the code; every listed licence pair is covered except the documented unknown cells.
Run: python3 -I tests/test_licence_compat.py"""
import datetime, json, os, pathlib, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import gateway as gw                    # noqa: E402
import sources.licence_compat as lc     # noqa: E402

T = '2026-10-31'
CODE_PLUGIN = P.parent / 'plugins' / 'code.md'
REQUIRED = ('MIT', 'BSD-2-Clause', 'BSD-3-Clause', 'Apache-2.0', 'ISC', 'MPL-2.0', 'LGPL-2.1-only', 'LGPL-3.0-only', 'GPL-2.0-only',
            'GPL-2.0-or-later', 'GPL-3.0-only', 'AGPL-3.0-only', 'Unlicense', 'CC0-1.0')
UNKNOWN_CELLS = {('Apache-2.0', 'LGPL-2.1-only', 'link'), ('LGPL-2.1-only', 'LGPL-3.0-only', 'copy'), ('LGPL-2.1-only', 'LGPL-3.0-only', 'modify'),
                 ('LGPL-2.1-only', 'LGPL-3.0-or-later', 'copy'), ('LGPL-2.1-only', 'LGPL-3.0-or-later', 'modify'),
                 ('LGPL-3.0-only', 'LGPL-2.1-only', 'link'), ('LGPL-3.0-or-later', 'LGPL-2.1-only', 'link')}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)
        self.env = dict(os.environ); os.environ['HOME'] = str(self.d); os.environ['VP_OFFLINE'] = '1'
        self.data0 = lc.DATA

    def tearDown(self):
        lc.DATA = self.data0
        os.environ.clear(); os.environ.update(self.env); self.tmp.cleanup()

    def ask(self, arg, use=None, T=T, plugin=CODE_PLUGIN):
        g = gw.Gateway([str(plugin)], T=T, run='r', state=self.d / 'st')
        return g.call('licence-compat', arg, use=use)

    def verdict(self, arg, use='copy', T=T):
        return self.ask(arg, use, T)['results']['answers'][0]


class Served(Base):
    def test_served_with_the_code_plugin_only_and_offline(self):
        other = self.d / 'other.md'
        other.write_text('# Other\n\n## Sources\n\n```sources\nengines: openalex\n```\n')
        self.assertIn('not declared', self.ask('MIT MIT', plugin=other)['refusal'])
        import sources as reg
        s = next(x for x in reg.SOURCES if x['name'] == 'licence-compat')
        self.assertEqual((s['access'], s['hosts']), ('local', {}))
        out = self.ask('MIT Apache-2.0')                                     # VP_OFFLINE=1: answered anyway
        self.assertEqual([a['use'] for a in out['results']['answers']], ['link', 'copy', 'modify'], 'all uses without --use')

    def test_disclaimer_first_and_direction(self):
        r = self.ask('MIT GPL-3.0-only', 'copy')['results']
        self.assertEqual(next(iter(r)), 'disclaimer'); self.assertTrue(r['disclaimer'].startswith('Not legal advice'))
        self.assertIn('X = licence of the receiving project', r['direction'])
        self.assertEqual(r['data']['file'], 'tools/licence_compat.json'); self.assertEqual(len(r['data']['sha256']), 64)


class Verdicts(Base):
    def test_table_answers_with_rule_and_sources(self):
        cases = {('GPL-3.0-only MIT', 'copy'): ('compatible_with_conditions', 'permissive-into-licensed'),
                 ('MIT GPL-3.0-only', 'link'): ('incompatible', 'gnu-into-non-gpl'),
                 ('GPL-2.0-only Apache-2.0', 'link'): ('incompatible', 'apache-into-gpl2-only'),
                 ('GPL-3.0-or-later Apache-2.0', 'modify'): ('compatible_with_conditions', 'apache-into-gnu-v3'),
                 ('GPL-2.0-or-later Apache-2.0', 'copy'): ('compatible_with_conditions', 'apache-into-gnu-or-later'),
                 ('MIT CC0-1.0', 'copy'): ('compatible', 'pd-into-any'),
                 ('Apache-2.0 MPL-2.0', 'modify'): ('compatible_with_conditions', 'mpl-into-non-gnu'),
                 ('MIT LGPL-2.1-only', 'link'): ('compatible_with_conditions', 'lgpl-link-into-non-gnu'),
                 ('MIT LGPL-3.0-only', 'copy'): ('incompatible', 'lgpl-copy-into-non-gnu'),
                 ('GPL-3.0-only AGPL-3.0-only', 'copy'): ('compatible_with_conditions', 'agpl3-into-gpl3'),
                 ('GPL-3.0-only GPL-2.0-only', 'copy'): ('incompatible', 'gpl2only-into-v3'),
                 ('Unlicense ISC', 'copy'): ('compatible_with_conditions', 'permissive-into-pd')}
        for (arg, use), (v, rule) in cases.items():
            with self.subTest(arg=arg, use=use):
                a = self.verdict(arg, use)
                self.assertEqual((a['verdict'], a['rule']), (v, rule))
                self.assertTrue(a['sources'] and all(s['url'].startswith('https://') for s in a['sources']))
        a = self.verdict('GPL-3.0-only Apache-2.0', 'modify')
        self.assertEqual({c['code'] for c in a['conditions']}, {'attribution', 'notice_file', 'state_changes_if_modified', 'combined_under_x'})
        self.assertTrue(all(c['text'] for c in a['conditions']))

    def test_aliases_and_case(self):
        a = self.verdict('mit gpl-3.0', 'copy')
        self.assertEqual((a['verdict'], a['y'], a['x']), ('incompatible', 'GPL-3.0-only', 'MIT'))
        self.assertEqual(a['alias'], {'gpl-3.0': 'GPL-3.0-only', 'mit': 'MIT'})

    def test_dual_licences(self):
        a = self.verdict('MIT GPL-3.0-only OR MIT', 'copy')                  # Y offered under two licences: the best option
        self.assertEqual((a['verdict'], a['retained']), ('compatible_with_conditions', 'MIT'))
        self.assertEqual([o['verdict'] for o in a['options']], ['incompatible', 'compatible_with_conditions'])
        a = self.verdict('"MIT OR GPL-2.0-only" Apache-2.0', 'copy')         # X offered under two licences: every option must hold
        self.assertEqual(a['verdict'], 'incompatible'); self.assertIn('every option', a['combined_as'])
        a = self.verdict('GPL-3.0-only (MIT AND BSD-3-Clause)', 'copy')
        self.assertEqual(a['verdict'], 'compatible_with_conditions')
        self.assertEqual({c['code'] for c in a['conditions']}, {'attribution', 'no_endorsement'})
        self.assertEqual(self.verdict('MIT (MIT AND GPL-2.0-only)', 'copy')['verdict'], 'incompatible')
        self.assertEqual(self.verdict('MIT GPL-2.0-only OR SSPL-1.0', 'copy')['verdict'], 'unknown', 'incompatible or unknown -> unknown')

    def test_unknown_never_compatible_by_default(self):
        a = self.verdict('MIT SSPL-1.0')
        self.assertEqual(a['verdict'], 'unknown'); self.assertIn('SSPL-1.0', a['reason'])
        a = self.verdict('LGPL-3.0-only LGPL-2.1-only', 'copy')
        self.assertEqual(a['verdict'], 'unknown'); self.assertIn('no rule', a['reason'])
        self.assertEqual(self.verdict('GPL-3.0-only GPL-2.0-only WITH Classpath-exception-2.0')['verdict'], 'unknown')
        a = self.verdict('GPL-3.0-or-later MIT', T='2006-01-01')
        self.assertEqual(a['verdict'], 'unknown'); self.assertIn('not published before T', a['reason'])

    def test_refusals(self):
        for arg, msg in (('MIT', 'two licences expected'), ('MIT (GPL-2.0-only', 'parenthesis'), ('MIT GPL-2.0-only extra', 'unexpected text'),
                         ('MIT; rm -rf GPL', 'characters outside'), ('MIT OR', 'expression ends early')):
            with self.subTest(arg=arg): self.assertIn(msg, self.ask(arg)['results']['refusal'])
        self.assertIn('use must be', self.ask('MIT MIT', use='fork')['results']['refusal'])
        self.assertIn('given twice', self.ask('MIT MIT use:link', use='copy')['results']['refusal'])
        self.assertEqual(self.ask('MIT MIT use:link')['results']['answers'][0]['use'], 'link')


class Data(Base):
    def write(self, mutate):
        d = json.loads(lc.DATA.read_text()); mutate(d)
        p = self.d / 'table.json'; p.write_text(json.dumps(d)); return p

    def test_malformed_tables_refused(self):
        def dup(d): d['rules'].append(dict(d['rules'][0], id='again'))
        def cond(d): d['rules'][0]['conditions'] = ['made_up']
        def src(d): d['rules'][0]['sources'] = []
        def unk(d): d['rules'][0]['verdict'] = 'unknown'
        for m, msg in ((dup, 'both cover'), (cond, 'unknown condition'), (src, 'sources'), (unk, 'verdict')):
            with self.subTest(m=m.__name__):
                with self.assertRaisesRegex(lc.MatrixError, msg): lc.load(self.write(m))

    def test_another_table_changes_the_answer_without_code(self):
        def flip(d):
            r = next(x for x in d['rules'] if x['id'] == 'gnu-into-non-gpl'); r['x'] = [x for x in d['groups']['non_gpl'] if x != 'MIT']
        lc.DATA = self.write(flip)
        a = self.verdict('MIT GPL-3.0-only', 'copy')
        self.assertEqual(a['verdict'], 'unknown', 'MIT receiving GPL code no longer covered: unknown, not compatible')

    def test_coverage(self):
        M = lc.load()
        lic = list(M['raw']['licences'])
        self.assertTrue(set(REQUIRED) <= set(lic))
        missing = {(y, x, u) for y in lic for x in lic for u in M['raw']['uses'] if (y, x, u) not in M['cells']}
        self.assertEqual(missing, UNKNOWN_CELLS, 'documented unknown cells only')
        self.assertFalse([r for r in M['raw']['rules'] if r['verdict'] == 'compatible' and r['conditions']])

    def test_no_licence_identifier_in_the_code(self):
        code = (P.parent / 'tools' / 'sources' / 'licence_compat.py').read_text()
        body = code.split('"""', 2)[2]                                       # after the module docstring
        for name in ('Apache-2.0', 'GPL-2.0', 'GPL-3.0', 'BSD-3', 'MPL-2.0', 'CC0', 'Unlicense', "'MIT'"):
            self.assertNotIn(name, body.split("'example':")[0], name)


if __name__ == '__main__':
    unittest.main()
