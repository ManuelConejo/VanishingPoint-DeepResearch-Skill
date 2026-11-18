# SPDX-License-Identifier: Apache-2.0
"""VP plugged on its REAL formats (regression specification R51, R52): the fixtures vp_real_q01 and vp_real_q05 are copies of two real VP
runs with the gateway journal stored at state/journal.jsonl for the tests."""
import importlib.util
import json
from pathlib import Path
import unittest

from .helpers import TempCase, load_tool, mutate, read_json, run_tool


class RealVPTest(TempCase):
    def setUp(self):
        super().setUp()
        self.check = load_tool('check')

    def test_real_run_layout(self):
        for name in ('vp_real_q01', 'vp_real_q05'):
            d = self.fx / name
            for f in ('card.json', 'verdicts.json', 'result.json', 'STUDIES.json', 'scope.md', 'REPORT.md',
                      'state/journal.jsonl'):
                self.assertTrue((d / f).exists(), '%s/%s' % (name, f))
            v = read_json(d / 'verdicts.json')
            self.assertIsInstance(v['claims'][0]['source'], str, 'real verdicts carry the source key as a string')

    def test_statuses_read_from_real_verdicts(self):
        st = self.check.reference_statuses(self.work('valid_vp_real'))
        self.assertEqual(st['doi:10.1080/08998280.2016.11929387'], 'FOUND')
        self.assertEqual(st['doi:10.1056/nejmoa1900100'], 'DISTORTED')
        self.assertEqual(st['pmid:32645234'], 'FOUND')

    def test_identifier_cross_checked_on_real_card(self):
        # Canonical URLs change only REPORT.md; Frontier resolves references from
        # card/verdicts/journal. Exercise the formatter against real VP layouts.
        formatter = Path(__file__).resolve().parents[2] / 'tools' / 'bibliography_links.py'
        spec = importlib.util.spec_from_file_location('vp_bibliography_links', formatter)
        links = importlib.util.module_from_spec(spec); spec.loader.exec_module(links)
        work = self.work('valid_vp_real')
        before = self.check.problems(work)
        statuses = self.check.reference_statuses(work)
        for name in ('vp_real_q01', 'vp_real_q05'):
            # TempCase copies fixtures into self.tmp; only this copy is writable.
            report = self.fx / name / 'REPORT.md'
            source = Path(__file__).resolve().parent / 'fixtures' / name / 'REPORT.md'
            original = source.read_bytes()
            self.assertTrue(report.resolve().is_relative_to(self.tmp.resolve()))
            self.assertNotEqual(report.resolve(), source.resolve())
            self.addCleanup(lambda p=source, data=original: self.assertEqual(p.read_bytes(), data))
            links.enrich_file(report)
            self.assertEqual(links.missing(report.read_text(encoding='utf-8')), [])
        self.assertEqual(self.check.problems(work), before)
        self.assertEqual(self.check.reference_statuses(work), statuses)
        mutate(self.work('valid_vp_real'), 'hypotheses.json',
               lambda d: d['hypotheses'][0]['for'][0].update(id='doi:10.1016/j.transci.2023.103839'))
        probs = self.check.problems(self.work('valid_vp_real'))
        self.assertTrue(any(p.startswith('[REF-MISMATCH]') for p in probs), probs)

    def test_claim_removed_by_vp_is_missing(self):
        """Q05: A48 was removed by VP after verification (absent from card.json and verdicts.json)."""
        def f(d):
            d['vp']['runs']['q05'] = '../vp_real_q05'
        mutate(self.work('valid_vp_real'), 'intake.json', f)
        mutate(self.work('valid_vp_real'), 'run.json', lambda d: d['steps'].append(
            {'step': 'vp_run', 'utc': '2025-08-01T09:30:00Z', 'duration_s': 'unknown', 'cost_usd': 'unknown',
             'vp_run': 'q05'}))
        mutate(self.work('valid_vp_real'), 'hypotheses.json', lambda d: d['rivals'][0]['for'].append(
            {'id': 'doi:10.1371/journal.pone.0002597', 'run': 'q05', 'claim': 'A48'}))
        probs = self.check.problems(self.work('valid_vp_real'))
        self.assertTrue(any(p.startswith('[REF-MISSING]') or p.startswith('[VP-RUN]') for p in probs), probs)

    def test_unverified_listed_on_card(self):
        """R52: SOURCE-UNAVAILABLE (Q05 A14) is accepted and listed under "Unverified references" at the top."""
        w = self.work('valid_vp_real')
        mutate(w, 'intake.json', lambda d: d['vp']['runs'].update(q05='../vp_real_q05'))
        mutate(w, 'intake.json', lambda d: d.update(T='2026-01-27'))
        mutate(w, 'run.json', lambda d: d['steps'].append(
            {'step': 'vp_run', 'utc': '2025-08-01T09:30:00Z', 'duration_s': 'unknown', 'cost_usd': 'unknown',
             'vp_run': 'q05'}))
        mutate(w, 'hypotheses.json', lambda d: d['rivals'][0]['for'].append(
            {'id': 'doi:10.1016/j.chb.2007.11.002', 'run': 'q05', 'claim': 'A14'}))
        self.assertEqual(self.check.problems(w), [])
        r = run_tool('card', w)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = (w / 'IDEA-CARD.md').read_text(encoding='utf-8')
        head = '\n'.join(text.splitlines()[:3])
        self.assertIn('Unverified references', head)
        self.assertIn('doi:10.1016/j.chb.2007.11.002 [SOURCE-UNAVAILABLE]', head)

    def test_real_card_from_q01(self):
        r = run_tool('card', self.work('valid_vp_real'))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = (self.work('valid_vp_real') / 'IDEA-CARD.md').read_text(encoding='utf-8')
        self.assertIn('doi:10.1016/j.transci.2023.103839 [FOUND]', text)
        self.assertIn('[DISTORTED]', text)
        self.assertNotIn('Unverified references', text)


if __name__ == '__main__':
    unittest.main()
