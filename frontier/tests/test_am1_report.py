# SPDX-License-Identifier: Apache-2.0
"""AM16-AM21, AM93: the one-page card stays, a complete IDEA-REPORT.md is assembled beside it."""
import re

from .am1_common import AM, NOVP, REBOUND, VP, load_tool, mutate, read_json, run_tool

LONG = ' '.join('longword%d' % i for i in range(120))     # about 1100 characters


class ReportTest(AM):
    def report(self, name=VP):
        self.assertEqual(self.card(name).returncode, 0)
        return (self.work(name) / 'IDEA-REPORT.md').read_text(encoding='utf-8')

    def test_am16_card_and_report_written(self):
        t = self.report()
        c = (self.work() / 'IDEA-CARD.md').read_text(encoding='utf-8')
        self.assertLessEqual(len(c.splitlines()), 80)
        self.assertTrue(t.strip())
        self.assertIn('# Idea report', t)

    def test_am17_nothing_truncated(self):
        def go(d):
            d['hypotheses'][0]['statement'] = LONG
        mutate(self.work(), 'hypotheses.json', go)
        t = self.report()
        c = (self.work() / 'IDEA-CARD.md').read_text(encoding='utf-8')
        self.assertIn(LONG, t)
        self.assertNotIn(LONG, c)
        self.assertIn('...', c)
        self.assertNotIn('...', t.replace('(unverified)', ''))

    def test_am17_no_more_lines_with_rebound(self):
        t = self.report(REBOUND)
        self.assertNotRegex(t, r'\(\+\d+ more')
        self.assertNotIn('...', t)
        for iid in ('N1', 'N2', 'N3', 'N4', 'N5', 'B1', 'B2'):
            self.assertRegex(t, r'(?m)^- %s ' % iid)

    def test_am18_everything_is_in_the_report(self):
        t = self.report()
        tests = read_json(self.work() / 'tests.json')
        for test in tests['tests']:
            self.assertIn(test['id'], t)
            self.assertIn(test['title'], t)
        hy = read_json(self.work() / 'hypotheses.json')
        for h in hy['hypotheses']:
            self.assertIn(h['statement'], t)
        cr = read_json(self.work() / 'critique.json')
        for it in cr['items']:
            self.assertIn(it['text'], t)

    def test_am18_draft_claims_section(self):
        self.add_draft()
        t = self.report()
        self.assertIn('## Free draft', t)
        for cid in ('D1', 'D2', 'D3', 'D4'):
            self.assertRegex(t, r'(?m)^- %s ' % cid)
        self.assertIn('unverified (memory)', t)
        self.assertIn('verified', t)

    def test_am19_stale_or_edited_report(self):
        self.assertEqual(self.card().returncode, 0)
        self.assertClean()
        p = self.work() / 'IDEA-REPORT.md'
        p.write_text(p.read_text(encoding='utf-8') + '\nhand-written line\n', encoding='utf-8')
        self.assertCode('[REPORT-STALE]')

    def test_am19_changed_input_makes_report_stale(self):
        self.assertEqual(self.card().returncode, 0)
        def go(d):
            d['reason'] = d['reason'] + ' Added after the report.'
        mutate(self.work(), 'recommendation.json', go)
        self.assertCode('[REPORT-STALE]')

    def test_am19_no_report_no_requirement(self):
        self.assertNoCode('[REPORT-STALE]')

    def test_am20_refused_card_writes_nothing(self):
        def go(d):
            d.pop('reason')
        mutate(self.work(), 'recommendation.json', go)
        r = self.card()
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.work() / 'IDEA-CARD.md').exists())
        self.assertFalse((self.work() / 'IDEA-REPORT.md').exists())

    def test_am21_fingerprint_only_changes_with_new_files(self):
        before = self.check.inputs_fingerprint(self.work())
        self.add_draft()
        after = self.check.inputs_fingerprint(self.work())
        self.assertNotEqual(before, after)
        for name in (NOVP,):
            self.assertEqual(len(self.check.inputs_fingerprint(self.work(name))), 64)

    def test_am93_fingerprint_includes_each_new_file(self):
        seen = {self.check.inputs_fingerprint(self.work())}
        for fname in ('free_draft.md', 'draft_claims.json', 'evidence_table.json', 'material.json', 'moment.json',
                      'context_candidates.json'):
            (self.work() / fname).write_text('{"x": 1}\n', encoding='utf-8')
            fp = self.check.inputs_fingerprint(self.work())
            self.assertNotIn(fp, seen, fname)
            seen.add(fp)

    def test_report_is_deterministic(self):
        a = self.report()
        b = self.report()
        self.assertEqual(a, b)
        self.assertRegex(a, r'<!-- frontier inputs sha256:[0-9a-f]{64} -->')
