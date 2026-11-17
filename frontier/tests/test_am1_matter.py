# SPDX-License-Identifier: Apache-2.0
"""AM60-AM73: matter (code, data, benchmarks) and moment through the gateway of VP (a fake one here), optional sources."""
import json
import os

from .am1_common import (AM, AS_OFS, FIND_IMPL, HF_DATA, NOVP, REBOUND, REPO_INFO, RISING, VP, load_tool, mutate,
                         read_json, run_tool, sha, totals_for, write_json)

CANNED = {"find-implementations|*": FIND_IMPL, "repo-info|owner/name": REPO_INFO, "search-hf-datasets|*": HF_DATA}


class MatterBase(AM):
    def setUp(self):
        super().setUp()
        self.vp = self.fake_vp(dict(CANNED))

    def matter(self, sub, *args, name=VP, env=None):
        return run_tool('matter', sub, self.work(name), *args, '--vp', self.vp, env=env)

    def material(self, name=VP):
        return read_json(self.work(name) / 'material.json')


class GatewayClientTest(AM):
    def test_am60_build_command(self):
        gw = load_tool('gwclient')
        cmd = gw.build_command(self.tmp / 'vp', '2026-11-14', 'matter', self.tmp / 'state', 'code', 'repo-info',
                               'owner/name', 10)
        self.assertEqual(cmd[1:3], ['-I', str(self.tmp / 'vp' / 'tools' / 'gateway.py')])
        for pair in (['--plugin', 'code'], ['--T', '2026-11-14'], ['--run', 'matter'],
                     ['--state', str(self.tmp / 'state')], ['--n', '10']):
            i = cmd.index(pair[0])
            self.assertEqual(cmd[i + 1], pair[1])
        self.assertIn('repo-info', cmd)
        self.assertIn('owner/name', cmd)
        self.assertTrue(all(isinstance(c, str) for c in cmd))

    def test_am60_vp_missing_refused(self):
        w = self.work()
        r = run_tool('matter', 'search', w, '--for', 'main', '--kind', 'code', '--query', 'title retrieval',
                     '--vp', self.tmp / 'nowhere')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('VP', r.stderr)
        self.assertFalse((w / 'matter').exists())

    def test_am60_environment_vp_missing_refused(self):
        w = self.work()
        env = dict(os.environ, FRONTIER_VP_DIR=str(self.tmp / 'nowhere'))
        r = run_tool('matter', 'search', w, '--for', 'main', '--kind', 'code', '--query', 'title retrieval',
                     env=env)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('VP', r.stderr)
        self.assertFalse((w / 'matter').exists())

    def test_am60_environment_vp_empty_refused(self):
        # A registered fake VP is a valid configured fallback; empty is explicit
        # and must refuse before even this fake gateway can be launched.
        from .helpers import copy_skill, set_config
        vp = self.fake_vp(dict(CANNED))
        skill = copy_skill(self.tmp / 'installed')
        set_config(skill, lambda cfg: cfg.update(vp_dir=str(vp)))
        w = self.work()
        env = dict(os.environ, FRONTIER_VP_DIR='')
        r = run_tool('matter', 'search', w, '--for', 'main', '--kind', 'code', '--query', 'title retrieval',
                     env=env, tools_dir=skill / 'tools')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('VP', r.stderr)
        self.assertFalse((w / 'matter').exists())
        self.assertEqual(self.fake_calls(), [])


class SearchTest(MatterBase):
    def test_am61_search_kinds(self):
        for kind, cmd in (('code', 'find-implementations'), ('dataset', 'search-hf-datasets'),
                          ('benchmark', 'search-hf-datasets')):
            r = self.matter('search', '--for', 'main', '--kind', kind, '--query', 'title retrieval ranking')
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out['command'], cmd)
            self.assertTrue((self.work() / out['envelope']).exists())
            self.assertTrue(out['candidates'])
        calls = self.fake_calls()
        self.assertEqual(len(calls), 3)
        for c in calls:
            a = c['argv']
            self.assertEqual(a[a.index('--T') + 1], '2026-11-14')
            self.assertEqual(a[a.index('--state') + 1], str(self.work() / 'matter' / 'state'))

    def test_am61_candidates_extracted(self):
        r = self.matter('search', '--for', 'main', '--kind', 'code', '--query', 'title retrieval ranking')
        names = [c['name'] for c in json.loads(r.stdout)['candidates']]
        self.assertEqual(names, ['owner/name', 'other/lib'])
        r = self.matter('search', '--for', 'main', '--kind', 'dataset', '--query', 'prices')
        c = json.loads(r.stdout)['candidates'][0]
        self.assertEqual((c['name'], c['date'], c['licence']), ('hfdataset:synthetic/tiles', '2025-02-01', 'cc-by-4.0'))

    def test_envelope_records_command_and_hash(self):
        r = self.matter('search', '--for', 'main', '--kind', 'code', '--query', 'title retrieval ranking')
        env = read_json(self.work() / json.loads(r.stdout)['envelope'])
        self.assertEqual((env['command'], env['T'], env['plugin']), ('find-implementations', '2026-11-14', 'code'))
        self.assertIn('gateway', env)

    def test_am62_repo_item_extracted_from_envelope(self):
        r = self.matter('repo', '--for', 'main', '--repo', 'owner/name')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        m = self.material()
        it = m['items'][0]
        self.assertEqual((it['for'], it['kind'], it['name'], it['licence'], it['last_activity']),
                         ('main', 'code', 'owner/name', 'MIT', '2026-03-02'))
        self.assertEqual(it['last_activity_basis'], 'last commit before T')
        self.assertEqual(it['via'], 'gateway')
        self.assertEqual(it['envelope_sha256'], sha(self.work() / it['envelope']))
        self.assertIn('catalogue', m['optional_sources'])
        self.assertIn('directions', m['optional_sources'])

    def test_am62_activity_after_T_is_never_written(self):
        canned = dict(CANNED)
        canned['repo-info|late/repo'] = {"results": {"id": "repo:late/repo", "licence": "Apache-2.0",
                                                     "pushed_at": "2026-12-01T00:00:00Z"}}
        self.vp = self.fake_vp(canned)
        r = self.matter('repo', '--for', 'main', '--repo', 'late/repo')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        it = self.material()['items'][0]
        self.assertIsNone(it['last_activity'])
        self.assertEqual(it['last_activity_basis'], 'unknown')
        self.assertEqual(it['licence'], 'Apache-2.0')

    def test_am62_push_date_before_T_marked_as_such(self):
        canned = dict(CANNED)
        canned['repo-info|old/repo'] = {"results": {"id": "repo:old/repo", "license": {"spdx_id": "GPL-3.0-only"},
                                                    "pushed_at": "2026-01-05T08:00:00Z"}}
        self.vp = self.fake_vp(canned)
        self.matter('repo', '--for', 'main', '--repo', 'old/repo')
        it = self.material()['items'][0]
        self.assertEqual((it['licence'], it['last_activity'], it['last_activity_basis']),
                         ('GPL-3.0-only', '2026-01-05', 'push date (as of now)'))

    def test_am63_add_dataset_from_search(self):
        r = self.matter('search', '--for', 'main', '--kind', 'dataset', '--query', 'prices')
        out = json.loads(r.stdout)
        r = self.matter('add', '--for', 'main', '--kind', 'dataset', '--envelope', out['envelope'], '--candidate', '0')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        it = self.material()['items'][0]
        self.assertEqual((it['kind'], it['name'], it['licence'], it['via']), ('dataset', 'hfdataset:synthetic/tiles', 'cc-by-4.0', 'gateway'))

    def test_am63_none_needs_a_search(self):
        r = self.matter('none', '--for', 'main', '--kind', 'benchmark')
        self.assertNotEqual(r.returncode, 0)
        self.matter('search', '--for', 'main', '--kind', 'benchmark', '--query', 'title retrieval benchmark')
        r = self.matter('none', '--for', 'main', '--kind', 'benchmark')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        s = self.material()['searched'][0]
        self.assertEqual((s['for'], s['kind'], s['result']), ('main', 'benchmark', 'not found'))
        self.assertTrue(s['queries'])


class MaterialCheckTest(MatterBase):
    def fill_main(self):
        self.matter('repo', '--for', 'main', '--repo', 'owner/name')

    def test_check_passes_with_main_item(self):
        self.fill_main()
        self.assertNoCode('[MAT')
        self.assertNoCode('[DATE]')

    def test_am64_every_idea_must_be_covered(self):
        self.matter('repo', '--for', 'main', '--repo', 'owner/name', name=REBOUND)
        p = self.assertCode('[MAT-COVER]', REBOUND)
        for iid in ('N1', 'N5', 'B1'):
            self.assertTrue(any(iid in x for x in p if x.startswith('[MAT-COVER]')), (iid, p))

    def test_am64_not_found_with_queries_covers(self):
        self.matter('repo', '--for', 'main', '--repo', 'owner/name', name=REBOUND)
        def go(d):
            ids = [i['id'] for f in ('rebound.json', 'rebound_after.json') for i in read_json(self.work(REBOUND) / f)['ideas']]
            for i in ids:
                d['searched'].append({"for": i, "kind": "code", "queries": ["a query written for this idea"],
                                      "result": "not found", "envelope": d['items'][0]['envelope']})
        self.mut(REBOUND, 'material.json', go)
        self.assertNoCode('[MAT-COVER]', REBOUND)
        def go2(d):
            d['searched'][0]['queries'] = []
        self.mut(REBOUND, 'material.json', go2)
        self.assertCode('[MAT-COVER]', REBOUND)

    def test_am64_unknown_for(self):
        self.fill_main()
        self.mut(VP, 'material.json', lambda d: d['items'][0].update({'for': 'N99'}))
        self.assertCode('[MAT-FOR]')

    def test_am65_envelope_checks(self):
        self.fill_main()
        it = self.material()['items'][0]
        env = self.work() / it['envelope']
        self.mut(VP, 'material.json', lambda d: d['items'][0].update(licence='GPL-2.0-only'))
        self.assertCode('[MAT-ENVELOPE]')
        self.fresh()
        self.fill_main()
        self.mut(VP, 'material.json', lambda d: d['items'][0].update(last_activity='2026-04-04'))
        self.assertCode('[MAT-ENVELOPE]')
        self.fresh()
        self.fill_main()
        e = self.work() / self.material()['items'][0]['envelope']
        e.write_text(e.read_text(encoding='utf-8') + '\n', encoding='utf-8')
        self.assertCode('[MAT-ENVELOPE]')
        self.fresh()
        self.fill_main()
        (self.work() / self.material()['items'][0]['envelope']).unlink()
        self.assertCode('[MAT-ENVELOPE]')

    def test_am66_dates(self):
        self.fill_main()
        self.mut(VP, 'material.json', lambda d: d['items'][0].update(last_activity='2027-01-01'))
        self.assertCode('[DATE]')

    def test_am66_journal_after_T(self):
        self.fill_main()
        j = self.work() / 'matter' / 'state' / 'journal.jsonl'
        lines = [json.loads(l) for l in j.read_text(encoding='utf-8').splitlines() if l.strip()]
        lines[0]['T'] = '2027-02-01'
        j.write_text('\n'.join(json.dumps(x) for x in lines) + '\n', encoding='utf-8')
        self.assertCode('[DATE]')

    def test_am66_envelope_T_after_T(self):
        self.fill_main()
        e = self.work() / self.material()['items'][0]['envelope']
        d = read_json(e)
        d['T'] = '2027-02-01'
        write_json(e, d)
        self.mut(VP, 'material.json', lambda m: m['items'][0].update(envelope_sha256=sha(e)))
        self.assertCode('[DATE]')

    def test_am67_host_item_flagged(self):
        self.fill_main()
        self.mut(VP, 'material.json', lambda d: d['items'].append(
            {"for": "main", "kind": "benchmark", "name": "SomeBench", "url": "https://example.org/b", "licence": "unknown",
             "last_activity": None, "last_activity_basis": "unknown", "via": "host", "note": "found by the host search tool"}))
        self.assertNoCode('[MAT-')
        w = self.check.warnings(self.work())
        self.assertTrue(any('not verified' in x and 'SomeBench' in x for x in w), w)
        self.assertEqual(self.card().returncode, 0)
        t = (self.work() / 'IDEA-REPORT.md').read_text(encoding='utf-8')
        self.assertRegex(t, r'SomeBench.*not verified')


class OptionalSourcesTest(MatterBase):
    HEAD = 'question\tnote\tid\tannee\ttitre\tmethode\tcapacite\tentree_sortie\tresultat\tverif\tampleur\tcode\n'

    def catalogue(self):
        p = self.tmp / 'catalogue.tsv'
        p.write_text(self.HEAD +
                     'U1\t3\tW11\t2024\tTitle length and retrieval ranking of citations\tTitleRank\tpredict citations from title retrieval\tpreprints to rank\tgain 3%\tok\tfort\thttps://github.com/acme/titlerank\n'
                     'U1\t2\tW12\t2023\tLoss functions for protein folding\tFoldLoss\tfold proteins\tsequences to structure\tgain\tok\tfaible\t\n',
                     encoding='utf-8')
        return p

    def directions(self):
        p = self.tmp / 'directions.tsv'
        p.write_text('sujet\tannee\tdirection\tliste\tsource\n'
                     'title length retrieval\t2018\trevisit title length effect on retrieval ranking\tA\tnote-1\n'
                     'title length retrieval\t2019\tunrelated direction about title length retrieval\tB\tnote-2\n', encoding='utf-8')
        return p

    def test_am68_skipped_when_absent(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('FRONTIER_')}
        r = self.matter('optional', '--for', 'main', env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        o = self.material()['optional_sources']
        for k in ('catalogue', 'directions'):
            self.assertEqual(o[k]['status'], 'skipped')
            self.assertGreater(len(o[k]['reason']), 20)
        self.assertNoCode('[MAT-OPTIONAL]')

    def test_am68_used_when_configured(self):
        env = dict(os.environ, FRONTIER_CATALOGUE=str(self.catalogue()), FRONTIER_DIRECTIONS_INDEX=str(self.directions()))
        r = self.matter('optional', '--for', 'main', env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        o = self.material()['optional_sources']
        self.assertEqual(o['catalogue']['status'], 'used')
        self.assertEqual([m['id'] for m in o['catalogue']['matches']], ['W11'])
        self.assertEqual(o['directions']['status'], 'used')
        self.assertEqual(len(o['directions']['matches']), 1)
        self.assertEqual(o['directions']['matches'][0]['liste'], 'A')
        self.assertNoCode('[MAT-CATALOGUE]')

    def test_am68_forged_match_refused(self):
        env = dict(os.environ, FRONTIER_CATALOGUE=str(self.catalogue()), FRONTIER_DIRECTIONS_INDEX=str(self.directions()))
        self.matter('optional', '--for', 'main', env=env)
        def go(d):
            d['optional_sources']['catalogue']['matches'].append({"id": "W999", "title": "A method that is not in the file"})
        self.mut(VP, 'material.json', go)
        self.assertCode('[MAT-CATALOGUE]')

    def test_am68_never_required(self):
        self.assertClean()
        self.matter('repo', '--for', 'main', '--repo', 'owner/name')
        self.assertClean()

    def test_am68_skip_without_reason_refused(self):
        self.matter('repo', '--for', 'main', '--repo', 'owner/name')
        self.mut(VP, 'material.json', lambda d: d['optional_sources']['catalogue'].update(reason='n/a'))
        self.assertCode('[MAT-OPTIONAL]')

    def test_am69_readers(self):
        cat = load_tool('catalogue')
        rows = cat.read_rows(self.catalogue())
        self.assertEqual([r['id'] for r in rows], ['W11', 'W12'])
        m = load_tool('matter')
        d = m.read_directions(self.directions())
        self.assertEqual([x['annee'] for x in d], ['2018'])


class MomentTest(MatterBase):
    def setUp(self):
        super().setUp()
        canned = dict(CANNED)
        canned.update(totals_for(RISING, AS_OFS))
        self.vp = self.fake_vp(canned)

    def moment(self, *extra):
        return self.matter('moment', '--query', 'title length citations', '--years', '5', *extra)

    def test_am70_moment_written(self):
        r = self.moment()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        m = read_json(self.work() / 'moment.json')
        self.assertEqual([s['as_of'] for s in m['series']], AS_OFS)
        self.assertEqual([s['total'] for s in m['series']], RISING)
        self.assertEqual([p['count'] for p in m['periods']], [100, 150, 200, 300, 450])
        self.assertEqual(m['reading'], 'rising')
        self.assertTrue(m['line'].startswith('Moment: rising'))
        calls = self.fake_calls()
        self.assertEqual(sorted(c['argv'][c['argv'].index('--T') + 1] for c in calls), AS_OFS)
        self.assertNoCode('[MOMENT')
        self.assertNoCode('[DATE]')

    def test_am71_reading_function(self):
        mod = load_tool('matter')
        th = load_tool('common').config()['moment']
        self.assertEqual(mod.moment_reading([100, 150, 200, 300, 450], th), 'rising')
        self.assertEqual(mod.moment_reading([100, 200, 300, 310, 300], th), 'saturating')
        self.assertEqual(mod.moment_reading([300, 150, 80, 90, 260], th), 'revived')
        self.assertEqual(mod.moment_reading([1, 2, 1, 0, 2], th), 'unclear')
        self.assertEqual(mod.moment_reading([100, 100, 100, 100, 100], th), 'unclear')

    def test_am71_periods_function(self):
        mod = load_tool('matter')
        series = [{"as_of": d, "total": t} for d, t in zip(AS_OFS, RISING)]
        per = mod.periods(series)
        self.assertEqual([p['count'] for p in per], [100, 150, 200, 300, 450])
        self.assertAlmostEqual(per[0]['per_year'], 100.0, delta=0.5)
        self.assertEqual((per[0]['from'], per[0]['to']), ('2021-11-14', '2022-11-14'))

    def test_am72_reading_must_recompute(self):
        self.moment()
        self.mut(VP, 'moment.json', lambda d: d.update(reading='saturating', line='Moment: saturating'))
        self.assertCode('[MOMENT-READING]')

    def test_am72_periods_and_thresholds(self):
        self.moment()
        self.mut(VP, 'moment.json', lambda d: d['periods'][0].update(count=999))
        self.assertCode('[MOMENT-READING]')
        self.fresh()
        self.moment()
        self.mut(VP, 'moment.json', lambda d: d['thresholds'].update(rise=0.01))
        self.assertCode('[MOMENT-READING]')

    def test_am72_series_rules(self):
        self.moment()
        self.mut(VP, 'moment.json', lambda d: d['series'][3].update(total=900))
        self.assertCode('[MOMENT-SERIES]')
        self.fresh()
        self.moment()
        self.mut(VP, 'moment.json', lambda d: d['series'].pop(0) and d['series'].pop(0) and d['series'].pop(0))
        self.assertCode('[MOMENT-SERIES]')
        self.fresh()
        self.moment()
        self.mut(VP, 'moment.json', lambda d: d['series'][-1].update(as_of='2027-03-01'))
        self.assertCode('[MOMENT-SERIES]')

    def test_am72_envelope(self):
        self.moment()
        self.mut(VP, 'moment.json', lambda d: d['series'][2].update(total=1260))
        self.assertAnyOf(['[MOMENT-ENVELOPE]'])
        self.fresh()
        self.moment()
        e = self.work() / read_json(self.work() / 'moment.json')['series'][1]['envelope']
        e.write_text(e.read_text(encoding='utf-8') + ' ', encoding='utf-8')
        self.assertCode('[MOMENT-ENVELOPE]')

    def assertAnyOf(self, codes):
        p = self.probs()
        self.assertTrue(any(x.startswith(c) for x in p for c in codes), p)

    def test_am73_card_lines_and_report(self):
        self.moment()
        self.matter('repo', '--for', 'main', '--repo', 'owner/name')
        r = self.card()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        c = (self.work() / 'IDEA-CARD.md').read_text(encoding='utf-8')
        self.assertEqual(len([l for l in c.splitlines() if l.startswith('Matter')]), 1, c)
        self.assertEqual(len([l for l in c.splitlines() if l.startswith('Moment')]), 1, c)
        self.assertLessEqual(len(c.splitlines()), 80)
        t = (self.work() / 'IDEA-REPORT.md').read_text(encoding='utf-8')
        for needle in ('## Matter', '## Moment', 'owner/name', 'MIT', '2026-03-02', '2021-11-14', 'index total',
                       'Optional sources', 'catalogue: skipped', 'directions index: skipped'):
            self.assertIn(needle, t)
