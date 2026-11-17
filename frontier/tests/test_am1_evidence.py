# SPDX-License-Identifier: Apache-2.0
"""AM50-AM56: the table of expected effects (evidence_table.json) and the test size computed by sim.py."""
import json

from .am1_common import AM, NOVP, VP, load_tool, mutate, read_json, run_tool, write_json


class Evidence(AM):
    def size(self, effect=0.8, sd=5.0):
        sim = load_tool('sim')
        return sim.needed_n('paired', effect, sd=sd)

    def table(self, name=VP, **over):
        e1 = {"id": "E1", "lead": "H1",
              "source": {"id": "arxiv:2101.00001", "run": "prior_art", "claim": "A2", "says": "rank depends on matches of title terms"},
              "sample": "Offline index of 4,200 scholarly records, queries drawn from titles",
              "measured_effect": {"value": 0.8, "unit": "rank positions", "text": "short titles ranked 0.8 positions higher"},
              "replication": "unknown", "needed_test_size": self.size()}
        e2 = {"id": "E2", "lead": "H2",
              "source": {"id": "doi:10.1000/titles.2019", "run": "prior_art", "claim": "A1", "says": "shorter titles received more citations"},
              "sample": "1.2 million records across 20 fields, citations at two years",
              "measured_effect": {"not_reported": "the abstract gives an association without an effect size"},
              "replication": "yes", "needed_test_size": {"not_computable": "no effect size or noise reported in the source"}}
        t = {"version": 1, "entries": [e1, e2]}
        t.update(over)
        write_json(self.work(name) / 'evidence_table.json', t)
        return t

    def test_am50_absent_is_fine_present_valid(self):
        self.assertClean()
        self.table()
        self.assertClean()

    def test_am50_schema(self):
        self.table(entries=[{"id": "E1", "lead": "H1"}])
        self.assertCode('[SCHEMA] evidence_table.json')

    def test_am51_every_load_bearing_hypothesis_covered(self):
        t = self.table()
        t['entries'] = t['entries'][:1]
        write_json(self.work() / 'evidence_table.json', t)
        self.assertCode('[EVID-COVER]')
        t['no_evidence'] = [{"lead": "H2", "searched": "VP prior-art run: queries on title length and citations at two years"}]
        write_json(self.work() / 'evidence_table.json', t)
        self.assertNoCode('[EVID-COVER]')

    def test_am51_unknown_lead(self):
        t = self.table()
        t['entries'][0]['lead'] = 'H9'
        write_json(self.work() / 'evidence_table.json', t)
        self.assertCode('[EVID-COVER]')

    def test_am52_source_goes_through_vp_verification(self):
        t = self.table()
        t['entries'][0]['source'] = {"id": "doi:10.1000/ghost.2021", "run": "prior_art", "claim": "A4"}
        write_json(self.work() / 'evidence_table.json', t)
        self.assertCode('[REF-ABSENT]')

    def test_am52_measured_effect_needs_a_source(self):
        t = self.table()
        t['entries'][0]['source'] = None
        write_json(self.work() / 'evidence_table.json', t)
        self.assertCode('[EVID-SOURCE]')

    def test_am52_without_vp_the_header_says_it(self):
        t = self.table(NOVP)
        for e in t['entries']:
            if e['source']:
                e['source'] = {"id": e['source']['id'], "says": e['source']['says']}
        write_json(self.work(NOVP) / 'evidence_table.json', t)
        self.assertNoCode('[REF-', NOVP)
        self.assertNoCode('[EVID-SOURCE]', NOVP)

    def test_am53_fields(self):
        for fn in (lambda e: e.update(sample='n/a'), lambda e: e.update(replication='maybe'),
                   lambda e: e['measured_effect'].update(unit='')):
            self.fresh()
            t = self.table()
            fn(t['entries'][0])
            write_json(self.work() / 'evidence_table.json', t)
            p = self.probs()
            self.assertTrue(any(x.startswith('[EVID-FIELD]') or x.startswith('[SCHEMA]') for x in p), p)

    def test_am54_size_rerun(self):
        t = self.table()
        t['entries'][0]['needed_test_size']['needed_n'] += 40
        write_json(self.work() / 'evidence_table.json', t)
        self.assertCode('[EVID-SIZE]')

    def test_am54_not_computable_needs_reason(self):
        t = self.table()
        t['entries'][1]['needed_test_size'] = {"not_computable": "n/a"}
        write_json(self.work() / 'evidence_table.json', t)
        self.assertCode('[EVID-SIZE]')

    def test_am54_size_required_when_effect_measured(self):
        t = self.table()
        t['entries'][0].pop('needed_test_size')
        write_json(self.work() / 'evidence_table.json', t)
        self.assertCode('[EVID-SIZE]')

    def test_am55_write_into(self):
        t = self.table()
        t['entries'][0].pop('needed_test_size')
        write_json(self.work() / 'evidence_table.json', t)
        r = run_tool('sim', '--design', 'paired', '--needed-n', '--effect', '0.8', '--sd', '5.0',
                     '--write-into', self.work() / 'evidence_table.json', '--entry', 'E1')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        e1 = read_json(self.work() / 'evidence_table.json')['entries'][0]
        self.assertEqual(e1['needed_test_size']['mode'], 'needed_n')
        self.assertNoCode('[EVID-SIZE]')

    def test_am55_unknown_entry(self):
        self.table()
        r = run_tool('sim', '--design', 'paired', '--needed-n', '--effect', '0.8', '--sd', '5.0',
                     '--write-into', self.work() / 'evidence_table.json', '--entry', 'E9')
        self.assertEqual(r.returncode, 2)

    def test_am56_card_line_and_report_table(self):
        self.table()
        self.assertEqual(self.card().returncode, 0, self.card().stdout)
        c = (self.work() / 'IDEA-CARD.md').read_text(encoding='utf-8')
        line = [l for l in c.splitlines() if l.startswith('Expected effects')]
        self.assertEqual(len(line), 1, c)
        self.assertIn('E1', line[0])
        self.assertLessEqual(len(c.splitlines()), 80)
        t = (self.work() / 'IDEA-REPORT.md').read_text(encoding='utf-8')
        self.assertIn('## Expected effects', t)
        for needle in ('E1', 'E2', 'Offline index of 4,200 scholarly records', 'replicated: unknown',
                       'replicated: yes', 'needed n', 'not computable'):
            self.assertIn(needle, t)
