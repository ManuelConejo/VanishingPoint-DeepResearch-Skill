#!/usr/bin/env python3
"""Offline tests of tools/check_code_facts.py: the repository facts asserted by a code-plugin run (licence, archived, last commit before T,
pushed_at, OSV advisories) are read from card.json claims and mechanisms.json licence fields (REPORT.md with --prose), attached to a repository
or a package, and checked against the GitHub and OSV engines: CONFIRMED / CONTRADICTED / UNCHECKABLE with a typed reason, never CONTRADICTED
when the access fails, never a value after T.
End to end: the annexes of the internal code bench of 2026-10-31 (C1 searxng AGPL, C4 maintenance of 5 repositories (first run and replay), C3
advisories at 2024-12-01) in tests/fixtures/code_facts/, replayed against the API answers recorded live on 2026-10-31 (recorded.json, trimmed
to the fields used; no credential was used or recorded). Unit cases use simulated engines. Transport replaced (CodeClient._send); no network.
Run: python3 -I tests/test_check_code_facts.py   (unittest; pytest-compatible)."""
import datetime, io, json, os, pathlib, sys, tempfile, unittest, urllib.error
from contextlib import redirect_stderr, redirect_stdout
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import check_code_facts as F   # noqa: E402
import code_sources as sc      # noqa: E402

FX = P / 'fixtures' / 'code_facts'
T31, TODAY = datetime.date(2026, 10, 31), datetime.date(2026, 10, 31)
SHA = 'd82b23c42d7a7e2402903e71e7a7f03014a00076'


class Replay:
    """Answers from recorded.json; a URL not recorded is a test failure (the tool asked for something unexpected)."""
    def __init__(self, fail=None):
        self.rec = json.loads((FX / 'recorded.json').read_text(encoding='utf-8')); self.calls, self.fail = [], fail

    def __call__(self, url, headers, body=None):
        self.calls.append(url)
        if self.fail: return self.fail(url)
        r = self.rec.get(url + ('\n' + body.decode() if body else ''))
        if r is None: raise AssertionError('unexpected URL ' + url)
        if r['status'] != 200: raise urllib.error.HTTPError(url, r['status'], 'x', {}, io.BytesIO(b''))
        return 200, json.dumps(r['json']).encode()


def card(claims, sources=None):
    return {'card_id': 't', 'sources': sources or {}, 'claims': [{'id': f'A{i}', 'text': t, 'source': {'key': k}} for i, (t, k) in enumerate(claims, 1)]}


class FakeGH:
    """Simulated GitHub engine for litl/backoff (MIT, archived) and o/noassert (NOASSERTION)."""
    def __init__(self, archived=True, error=None): self.archived, self.error, self.extra = archived, error, {}
    def _e(self):
        if self.error: raise ValueError(self.error)
    def info(self, repo):
        self._e()
        if repo not in ('litl/backoff', 'o/noassert', 'o/new'): raise ValueError('provider_error:HTTP404')
        return {'repo': repo, 'default_branch': 'master', 'archived': self.archived, 'pushed_at': '2024-05-02T21:50:08Z' if repo != 'o/new' else '2026-11-01T00:00:00Z',
                'created_at': '2014-01-01T00:00:00Z'}
    def head_before(self, repo, T):
        self._e(); return self.resolve(repo, SHA)
    def barrier(self, repo, r, B, extra=None):                          # the gateway barrier without backdate signals (none simulated here)
        why = sc.GitHubRepo.gate(r, B.T)
        return ('after T or not datable: ' + why) if why else None if B.ok(None, r.get('date')) else 'after T: commit dated on/after T (or undated)'
    def head_gated(self, repo, B, extra=None):
        r = self.head_before(repo, B.T); why = self.barrier(repo, r, B, extra)
        return (None, why) if why else (r, None)
    def resolve(self, repo, sha):
        self._e()
        return {'sha': SHA, 'date': '2023-01-20T19:02:28Z', 'author_date': '2023-01-19T23:30:00Z', 'in_default_branch': True, 'repo_created_at': '2014-01-01T00:00:00Z'}
    def licence(self, repo, ref=None):
        self._e(); return {'spdx': 'MIT' if repo == 'litl/backoff' else 'NOASSERTION', 'path': 'LICENSE'}


class FakeOSV:
    def __init__(self, modified='2024-01-01T00:00:00Z', published='2023-10-02T00:00:00Z', error=None): self.mod, self.pub, self.error = modified, published, error
    def get(self, ident):
        if self.error: raise ValueError(self.error)
        if ident not in ('PYSEC-2023-192', 'CVE-2023-43804'): raise ValueError('provider_error:HTTP404')
        return {'id': 'PYSEC-2023-192', 'aliases': ['CVE-2023-43804', 'GHSA-v845-jxx5-vc9f'], 'published': self.pub, 'modified': self.mod,
                'affected': [{'package': {'name': 'urllib3', 'ecosystem': 'PyPI'}, 'ranges': [{'type': 'ECOSYSTEM', 'events': [{'introduced': '0'}, {'fixed': '1.26.17'}]},
                                                                                             {'type': 'GIT', 'events': [{'fixed': '0' * 40}]}]}]}
    def query(self, system, pkg, ver):
        if self.error: raise ValueError(self.error)
        return [{'id': 'PYSEC-2023-192', 'published': self.pub, 'modified': self.mod}] if (pkg, ver) == ('urllib3', '1.26.15') else []
    def query_commit(self, sha): return self.query('pypi', 'urllib3', '1.26.15') if sha == SHA else []


class CheckCodeFacts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)
        self.env = dict(os.environ); os.environ['HOME'] = str(self.d); os.environ.pop('VP_GITHUB_TOKEN', None); os.environ.pop('VP_OFFLINE', None)
        self.send0 = sc.CodeClient._send

    def tearDown(self):
        sc.CodeClient._send = self.send0
        os.environ.clear(); os.environ.update(self.env); self.tmp.cleanup()

    def engines(self, t):
        c = sc.CodeClient(cache_dir=self.d / 'state'); c.sleep = lambda s: None; c._send = t
        return sc.GitHubRepo(c), sc.Vulns(c)

    def run_case(self, case, T, t=None, **kw):
        gh, osv = self.engines(t or Replay())
        d = FX / case
        return F.check([d / f for f in F.DEFAULT_FILES if (d / f).exists()], T, run_dir=d, gh=gh, osv=osv, today=TODAY, **kw)

    def write(self, data, name='card.json'):
        p = self.d / name; p.write_text(json.dumps(data)); return p

    def test_config(self):
        cfg = json.loads((P.parent / 'tools' / 'config.json').read_text(encoding='utf-8'))['code_facts']
        self.assertEqual((F.CURRENT_DAYS, F.DATE_TOL), (cfg['current_value_days'], cfg['commit_date_tolerance_days']))

    def test_bench_c4_replay_end_to_end(self):
        rep = self.run_case('c4', T31)
        s = rep['summary']
        self.assertEqual((s['facts'], s['confirmed'], s['contradicted'], s['uncheckable']), (19, 18, 0, 1))
        self.assertEqual(s['by_type']['last_commit'], {'CONFIRMED': 5, 'CONTRADICTED': 0, 'UNCHECKABLE': 0})
        by = {(f['type'], f['repo'], str(f['claimed'])): f for f in rep['facts']}
        retry = by[('licence', 'invl/retry', 'Apache-2.0')]
        self.assertEqual((retry['status'], retry['reason_type'], retry['observed']), ('UNCHECKABLE', 'no_api', 'NOASSERTION'),
                         'a licence GitHub does not identify is never contradicted: the file is to be read')
        self.assertEqual(by[('licence', 'invl/retry', 'NOASSERTION')]['status'], 'CONFIRMED')
        b = by[('archived', 'litl/backoff', 'True')]
        self.assertEqual((b['status'], b['as_of'], sorted(b['where'])), ('CONFIRMED', 'now', ['card.json:claims.A19', 'card.json:claims.A8']))
        lc = by[('last_commit', 'jd/tenacity', '2026-10-12')]
        self.assertEqual((lc['status'], lc['commit']), ('CONFIRMED', '32ac68f0941319c0d2f4fb927f96e4ee29bb46c6'))
        self.assertEqual(by[('pushed_at', 'litl/backoff', '2024-05-02')]['status'], 'CONFIRMED')
        self.assertEqual(F.exit_code(rep), 0); self.assertEqual(F.exit_code(rep, strict=True), 1)

    def test_bench_c4_first_run_c1_and_c3(self):
        s = self.run_case('c4-first', T31)['summary']
        self.assertEqual((s['facts'], s['confirmed'], s['contradicted'], s['uncheckable'], s['unparsed']), (5, 4, 0, 1, 1),
                         'licences of the ecosyste.ms package records, attached by the name part of the repositories')
        rep = self.run_case('c1', T31, x_name='hynek/stamina')
        lic = {(f['repo'], f.get('sha')): f for f in rep['facts']}
        y = lic[('searxng/searxng', 'c15647b5a5921858d5147d291c658fbda3cba12c')]
        self.assertEqual((y['status'], y['claimed'], y['observed'], y['basis']), ('CONFIRMED', 'AGPL-3.0', 'AGPL-3.0', 'GitHub licence detection at the pinned commit'))
        self.assertTrue({'card.json:claims.A1', 'card.json:claims.A16', 'mechanisms.json:[0].licence'} <= set(y['where']),
                        '"GNU AGPL version 3", "AGPL" and "Y is AGPL-3.0": one fact, Y pinned by capsule.json')
        self.assertEqual((rep['summary']['facts'], rep['summary']['confirmed']), (2, 2), 'the unpinned "X is MIT" merged with the pinned A2')
        self.assertEqual([u['why'] for u in rep['unparsed']], ['several licences in one clause'])
        no_x = self.run_case('c1', T31)
        x = next(f for f in no_x['facts'] if 'card.json:claims.A2' in f['where'])
        self.assertEqual((x['status'], x['reason_type']), ('UNCHECKABLE', 'no_target'), 'host code X without --x-name')
        rep = self.run_case('c3', datetime.date(2024, 12, 1))
        self.assertEqual(rep['summary']['by_type'], {'vulnerability': {'CONFIRMED': 6, 'CONTRADICTED': 0, 'UNCHECKABLE': 0}})
        fx = {(f['claimed'], f['version']): f for f in rep['facts']}
        self.assertEqual(fx[('fixed_in', '2.0.6')]['observed'], ['1.26.17', '2.0.6'], 'GIT ranges (commits) are not versions')
        self.assertEqual(fx[('not_affected', '3.1.2')]['osv'], 'GHSA-g3rq-g295-4j3m')

    def test_prose_report(self):
        gh, osv = self.engines(Replay())
        rep = F.check([FX / 'c4' / 'card.json', FX / 'c4' / 'REPORT.md'], T31, run_dir=FX / 'c4', gh=gh, osv=osv, prose=True, today=TODAY)
        prose = [f for f in rep['facts'] if all(w.startswith('REPORT.md') for w in f['where'])]
        self.assertEqual(prose, [], 'every prose fact of C4 is also asserted by the card (merged)')
        self.assertEqual(rep['summary']['contradicted'], 0)
        self.assertTrue(any(w.startswith('REPORT.md:7') for f in rep['facts'] for w in f['where']), 'sentences starting with <owner>/<name>')
        self.assertFalse(any(w.startswith('REPORT.md:96') for f in rep['facts'] for w in f['where']), 'methodology appendix skipped')

    def test_access_failures_are_never_contradictions(self):
        fails = {'network': lambda u: (_ for _ in ()).throw(OSError('down')),
                 'rate_limited': lambda u: (_ for _ in ()).throw(urllib.error.HTTPError(u, 403, 'x', {'X-RateLimit-Remaining': '0'}, io.BytesIO(b''))),
                 'access_denied': lambda u: (_ for _ in ()).throw(urllib.error.HTTPError(u, 403, 'x', {}, io.BytesIO(b''))),
                 'not_found': lambda u: (_ for _ in ()).throw(urllib.error.HTTPError(u, 404, 'x', {}, io.BytesIO(b'')))}
        for want, fail in fails.items():
            for case, T in (('c4', T31), ('c3', datetime.date(2024, 12, 1))):
                self.tmp.cleanup(); self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)
                s = self.run_case(case, T, t=Replay(fail))['summary']
                self.assertEqual((s['confirmed'], s['contradicted'], s['uncheckable_reasons']), (0, 0, {want: s['facts']}), (want, case))
        s = F.check([FX / 'c4' / 'card.json'], T31, today=TODAY)['summary']
        self.assertEqual((s['contradicted'], s['uncheckable_reasons']), (0, {'network': 19}), 'offline: no engine')

    def test_extraction_forms(self):
        p = self.write(card([('litl/backoff is not maintained (archived, last commit 2023-01-20 before the window opening 2025-10-31).', 'S1'),
                             ('The archived flag is not established; the last commit before T=2026-10-31 was not read.', 'S1'),
                             ('Licences: Y is AGPL-3.0 [1], X is MIT [2], so no AGPL text may be copied.', None),
                             ('The repository is licensed under the Apache License, Version 2.0.', 'S1'),
                             ('Its repository-wide pushed_at (2024-05-02) differs.', 'S1')],
                            {'S1': {'code': 'repo:litl/backoff@' + SHA, 'title': 't'}}))
        e = F.extract([p], repo='o/y', x_name='o/x')
        got = sorted((f['type'], f['repo'], str(f['claimed']), f['where'][-2:]) for f in e['facts'])
        self.assertEqual(got, [('archived', 'litl/backoff', 'True', 'A1'), ('last_commit', 'litl/backoff', '2023-01-20', 'A1'),
                               ('licence', 'litl/backoff', 'Apache-2.0', 'A4'), ('licence', 'o/x', 'MIT', 'A3'), ('licence', 'o/y', 'AGPL-3.0', 'A3'),
                               ('pushed_at', 'litl/backoff', '2024-05-02', 'A5')],
                         'negated flag, T and window dates, "no AGPL text" are not facts; the source pins the repository')
        self.assertEqual(next(f['sha'] for f in e['facts'] if f['where'].endswith('A4')), SHA)
        for text, lic in (('licensed GNU Affero General Public License v3', 'AGPL-3.0'), ('is BSD 3-Clause licensed', 'BSD-3-Clause'),
                          ('licence: GPLv2', 'GPL-2.0'), ('licence LGPL-2.1', 'LGPL-2.1'), ('licence MPL 2.0', 'MPL-2.0')):
            f, _ = F._facts_of('o/y ' + text, 'w', F.Targets({'o/y'}, None, None), {'side': 'Y'})
            self.assertEqual([x['claimed'] for x in f], [lic], text)
        self.assertTrue(F._lic_match('GPL', 'GPL-3.0-or-later') and F._lic_match('AGPL-3.0', 'AGPL-3.0-only') and not F._lic_match('GPL', 'LGPL-2.1'))

    def test_dates_current_values_and_T(self):
        p = self.write(card([('litl/backoff is not archived.', 'S'), ('litl/backoff is archived.', 'S'), ('The last commit of litl/backoff is dated 2023-01-21.', 'S'),
                             ('The last commit of litl/backoff is dated 2023-01-25.', 'S'), ('The last commit of litl/backoff is dated 2026-11-02.', 'S'),
                             ('litl/backoff is licensed GPL-3.0.', 'S'), ('o/noassert is licensed MIT.', 'S2'), ('o/new has pushed_at 2026-10-01.', 'S3')],
                            {'S': {'code': 'repo:litl/backoff@' + SHA}, 'S2': {'code': 'repo:o/noassert@' + SHA}, 'S3': {'code': 'repo:o/new@' + SHA}}))
        st = lambda rep: {(f['type'], f['repo'], str(f['claimed'])): (f['status'], f.get('reason_type')) for f in rep['facts']}
        fresh = st(F.check([p], T31, gh=FakeGH(), today=TODAY))
        self.assertEqual(fresh[('archived', 'litl/backoff', 'False')], ('CONTRADICTED', None), 'current value within code_facts.current_value_days')
        self.assertEqual(fresh[('last_commit', 'litl/backoff', '2023-01-21')], ('CONFIRMED', None), 'within code_facts.commit_date_tolerance_days')
        self.assertEqual(fresh[('last_commit', 'litl/backoff', '2023-01-25')], ('CONTRADICTED', None))
        self.assertEqual(fresh[('last_commit', 'litl/backoff', '2026-11-02')], ('UNCHECKABLE', 'after_T'), 'a post-T date is a leak, not a check')
        self.assertEqual(fresh[('licence', 'litl/backoff', 'GPL-3.0')], ('CONTRADICTED', None))
        self.assertEqual(fresh[('licence', 'o/noassert', 'MIT')], ('UNCHECKABLE', 'no_api'))
        self.assertEqual(fresh[('pushed_at', 'o/new', '2026-10-01')], ('UNCHECKABLE', 'after_T'), 'pushed after T: the value at T is not observable')
        late = st(F.check([p], T31, gh=FakeGH(), today=T31 + datetime.timedelta(days=F.CURRENT_DAYS + 1)))
        self.assertEqual((late[('archived', 'litl/backoff', 'False')], late[('archived', 'litl/backoff', 'True')]), (('UNCHECKABLE', 'after_T'), ('CONFIRMED', None)),
                         'long after T: agreement confirms (as_of now), disagreement is uncheckable')

    def test_osv_facts(self):
        p = self.write(card([('PYSEC-2023-192 (CVE-2023-43804) for urllib3 is fixed in 1.26.17.', None),
                             ('PYSEC-2023-192 for urllib3 is fixed in 1.26.16.', None),
                             ('PYSEC-2023-192 does not affect urllib3 1.26.15.', None), ('CVE-2023-43804 affects urllib3 1.26.15.', None),
                             ('There is no known vulnerability for urllib3 1.26.15 (PyPI).', None),
                             ('PYSEC-2023-192 and PYSEC-2099-1 for urllib3 are fixed in 1.26.17.', None),
                             (f'No known vulnerabilities affect commit {SHA}.', None)]))
        T = datetime.date(2024, 12, 1)
        st = lambda osv, today=TODAY: [(f['claimed'], f.get('version'), f['status'], f.get('reason_type')) for f in F.check([p], T, osv=osv, today=today)['facts']]
        self.assertEqual(st(FakeOSV()), [('fixed_in', '1.26.17', 'CONFIRMED', None), ('fixed_in', '1.26.16', 'CONTRADICTED', None),
                                         ('not_affected', '1.26.15', 'CONTRADICTED', None), ('affected', '1.26.15', 'CONFIRMED', None),
                                         ('none_for_version', '1.26.15', 'CONTRADICTED', None), ('fixed_in', '1.26.17', 'UNCHECKABLE', 'no_target'),
                                         ('none_for_commit', None, 'CONTRADICTED', None)])
        edited = st(FakeOSV(modified='2025-06-01T00:00:00Z'))
        self.assertEqual([x[2:] for x in edited[:3]], [('CONFIRMED', None), ('UNCHECKABLE', 'after_T'), ('UNCHECKABLE', 'after_T')],
                         'a record modified after T only confirms')
        self.assertTrue(all(x[3] == 'after_T' for x in st(FakeOSV(published='2025-01-01T00:00:00Z'))[:4]), 'advisory published after T: never used')
        self.assertTrue(all(x[2] == 'UNCHECKABLE' and x[3] == 'network' for x in st(FakeOSV(error='transport_error:URLError'))[:5]))

    def test_cli(self):
        def main(*a):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err): rc = F.main(list(a))
            return rc, out.getvalue(), err.getvalue()
        rc, out, _ = main(str(FX / 'c4'), '--offline', '--today', '2026-10-31')
        rep = json.loads(out)
        self.assertEqual((rc, rep['T'], rep['summary']['uncheckable']), (0, '2026-10-31', 19), 'T read from run.json')
        self.assertEqual(main(str(FX / 'c4'), '--offline', '--strict')[0], 1)
        self.assertEqual(main(str(FX / 'c1'), '--offline')[0], 2, 'no T: usage error')
        self.assertEqual(main(str(FX / 'c1'), '--offline', '--T', '2026-10-31', '--repo', 'bad')[0], 2)
        self.assertEqual(main(str(FX / 'c1'), '--offline', '--T', '2026-10-31')[0], 0)
        self.assertEqual(main()[0], 2)


if __name__ == '__main__':
    unittest.main()
